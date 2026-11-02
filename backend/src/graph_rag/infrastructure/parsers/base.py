"""Shared helpers for parser adapters."""

from __future__ import annotations

import asyncio
import multiprocessing
import signal
from collections.abc import Callable
from typing import Any

from graph_rag.shared.exceptions import ConfigurationError, ParserError, TransientError

# Default ceiling for a single blocking parser SDK call (Docling/MinerU/Marker/
# PaddleOCR conversion). A stuck layout/table model or a hung I/O call inside
# the SDK otherwise blocks PARSE indefinitely -- there is no way to recover
# an ingestion run stuck awaiting a call that never returns. Generous enough
# for legitimately large/complex documents; only ever engages when something
# has actually stalled well past normal parse time.
DEFAULT_PARSE_TIMEOUT_SECONDS = 600.0


def require_optional_dependency(module_name: str, extra_name: str = "parsers") -> object:
    """Import an optional parser dependency or raise a configuration error."""
    try:
        return __import__(module_name)
    except ImportError as exc:
        raise ConfigurationError(
            f"Optional dependency '{module_name}' is not installed",
            details={"extra": extra_name, "module": module_name},
            cause=exc,
        ) from exc


async def run_parser_sync[T](
    fn: Callable[[], T],
    *,
    timeout_seconds: float | None = None,
) -> T:
    """Run blocking parser SDK calls off the event loop with an optional timeout."""
    try:
        if timeout_seconds is None or timeout_seconds <= 0:
            return await asyncio.to_thread(fn)
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise TransientError(
            "Parser execution timed out",
            details={"timeout_seconds": timeout_seconds},
            cause=exc,
        ) from exc
    except ConfigurationError:
        raise
    except ParserError:
        raise
    except TransientError:
        raise
    except Exception as exc:
        raise ParserError("Parser execution failed", cause=exc) from exc


def _isolatable(fn: Callable[..., Any]) -> bool:
    """Module-level functions can be spawned. Lambdas and bound methods cannot."""
    name = getattr(fn, "__name__", "")
    qualname = getattr(fn, "__qualname__", "")
    return bool(name) and name.isidentifier() and qualname == name


def _isolated_child(fn: Callable[..., Any], args: tuple, kwargs: dict, queue: Any) -> None:
    try:
        queue.put(("ok", fn(*args, **kwargs)))
    except Exception as exc:
        queue.put(("err", type(exc).__name__, str(exc)))


def _isolated_sync(
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    timeout_seconds: float | None,
) -> Any:
    """Run ``fn`` in a child so SIGILL cannot kill the worker.

    Exit code 132 is 128+SIGILL. A thread or ``except Exception`` cannot catch
    that signal, which is why a poison document restarted the worker forever.
    """
    ctx = multiprocessing.get_context("spawn")
    queue: Any = ctx.Queue()
    proc = ctx.Process(target=_isolated_child, args=(fn, args, kwargs, queue))
    proc.start()
    join_for = timeout_seconds if timeout_seconds and timeout_seconds > 0 else None
    proc.join(join_for)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
        raise TransientError(
            "Parser execution timed out",
            details={"timeout_seconds": timeout_seconds},
        )
    exit_code = proc.exitcode
    if exit_code not in (0, None):
        signaled = exit_code < 0
        reported = (128 - exit_code) if signaled else exit_code
        signame = None
        if signaled:
            try:
                signame = signal.Signals(-exit_code).name
            except ValueError:
                signame = str(-exit_code)
        raise ParserError(
            "Native parser process aborted",
            details={"exit_code": reported, "signal": signame},
        )
    try:
        status, *rest = queue.get_nowait()
    except Exception as exc:
        raise ParserError("Native parser process returned no result", cause=exc) from exc
    if status == "ok":
        return rest[0]
    error_name = rest[0] if rest else "Exception"
    message = rest[1] if len(rest) > 1 and rest[1] else "Parser execution failed"
    if error_name == "ConfigurationError":
        raise ConfigurationError(message)
    if error_name == "TransientError":
        raise TransientError(message)
    raise ParserError(message)


async def run_callable_isolated[T](
    fn: Callable[..., T],
    *args: Any,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> T:
    """Run a picklable parser function in a child process.

    Test doubles and lambdas stay on the thread path so unit tests do not pay
    for a spawned interpreter.
    """
    if not _isolatable(fn):
        return await run_parser_sync(lambda: fn(*args, **kwargs), timeout_seconds=timeout_seconds)
    return await asyncio.to_thread(_isolated_sync, fn, args, kwargs, timeout_seconds)
