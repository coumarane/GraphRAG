"""Shared helpers for parser adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from graph_rag.shared.exceptions import ConfigurationError, ParserError, TransientError


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
