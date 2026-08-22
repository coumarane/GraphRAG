"""Structured logging configuration based on structlog."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, TextIO, cast

import structlog

from graph_rag.shared.redaction import structlog_redaction_processor

_CONFIGURED = False


def _add_service_context(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Ensure standard service fields exist when absent."""
    event_dict.setdefault("service", "enterprise-rag")
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    json_logs: bool = False,
    stream: TextIO | None = None,
    service_name: str = "enterprise-rag",
) -> None:
    """Configure stdlib logging and structlog processors.

    Safe to call multiple times; subsequent calls update the log level and
    rebuild the processor chain.
    """
    global _CONFIGURED

    log_level = getattr(logging, level.upper(), logging.INFO)
    output = stream if stream is not None else sys.stdout

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        _add_service_context,
        structlog_redaction_processor,
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.PATHNAME,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.FUNC_NAME,
            }
        ),
    ]

    renderer: structlog.types.Processor
    if json_logs:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=output.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(output)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Keep noisy third-party loggers at WARNING unless debugging.
    for noisy in ("httpx", "httpcore", "asyncio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog bound logger, configuring defaults if needed."""
    if not _CONFIGURED:
        configure_logging()
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def bind_context(**kwargs: Any) -> None:
    """Bind correlation fields (tenant, document, run IDs) into contextvars."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear structured logging contextvars."""
    structlog.contextvars.clear_contextvars()


def reset_logging_state() -> None:
    """Reset configuration flag. Intended for tests only."""
    global _CONFIGURED
    _CONFIGURED = False
    structlog.contextvars.clear_contextvars()
    root = logging.getLogger()
    root.handlers.clear()
