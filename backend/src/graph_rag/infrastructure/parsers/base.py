"""Shared helpers for parser adapters."""

from __future__ import annotations

import asyncio
import os
import pickle
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
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


def _isolated_sync(
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    timeout_seconds: float | None,
) -> Any:
    """Run ``fn`` in a child so SIGILL cannot kill the worker.

    Exit code 132 is 128+SIGILL. A thread or ``except Exception`` cannot catch
    that signal. ``multiprocessing`` spawn still forks the parent, and a
    PDFium/OpenMP atfork handler then aborts the worker itself.
    """
    with tempfile.TemporaryDirectory(prefix="parser-isolate-") as tmp:
        directory = Path(tmp)
        job_path = directory / "job.pkl"
        result_path = directory / "result.pkl"
        job_path.write_bytes(pickle.dumps((fn, args, kwargs)))
        env = os.environ.copy()
        pythonpath = os.pathsep.join(sys.path)
        if env.get("PYTHONPATH"):
            pythonpath = pythonpath + os.pathsep + env["PYTHONPATH"]
        env["PYTHONPATH"] = pythonpath
        proc = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-m",
                "graph_rag.infrastructure.parsers.isolate_main",
                str(job_path),
                str(result_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
        )
        join_for = timeout_seconds if timeout_seconds and timeout_seconds > 0 else None
        try:
            _, stderr = proc.communicate(timeout=join_for)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=5)
            raise TransientError(
                "Parser execution timed out",
                details={"timeout_seconds": timeout_seconds},
            ) from None
        exit_code = proc.returncode
        if exit_code not in (0, None):
            signaled = exit_code is not None and exit_code < 0
            reported = (128 - exit_code) if signaled and exit_code is not None else exit_code
            signame = None
            if signaled and exit_code is not None:
                try:
                    signame = signal.Signals(-exit_code).name
                except ValueError:
                    signame = str(-exit_code)
            raise ParserError(
                "Native parser process aborted",
                details={"exit_code": reported, "signal": signame},
            )
        try:
            status, *rest = pickle.loads(result_path.read_bytes())  # noqa: S301
        except Exception as exc:
            detail = (stderr or b"").decode("utf-8", "replace")[-240:]
            raise ParserError(
                "Native parser process returned no result",
                details={"stderr": detail},
                cause=exc,
            ) from exc
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
