"""Lightweight tracing helpers with optional OpenTelemetry backing."""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from graph_rag.domain.ids import new_id
from graph_rag.shared.logging import bind_context, get_logger
from graph_rag.shared.redaction import redact_mapping

logger = get_logger(__name__)


@dataclass
class SpanRecord:
    """In-memory span for tests when OTel is unavailable."""

    name: str
    trace_id: str
    span_id: str
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    duration_ms: float | None = None
    error: str | None = None


_SPANS: list[SpanRecord] = []
_OTEL_TRACER: Any | None = None
_OTEL_CONFIGURED = False


def configure_tracing(*, service_name: str = "enterprise-rag", enabled: bool = True) -> None:
    """Best-effort OpenTelemetry TracerProvider setup."""
    global _OTEL_TRACER, _OTEL_CONFIGURED
    if not enabled:
        _OTEL_TRACER = None
        _OTEL_CONFIGURED = True
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError:
        _OTEL_TRACER = None
        _OTEL_CONFIGURED = True
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    trace.set_tracer_provider(provider)
    _OTEL_TRACER = trace.get_tracer(service_name)
    _OTEL_CONFIGURED = True


def recorded_spans() -> list[SpanRecord]:
    return list(_SPANS)


def clear_spans() -> None:
    _SPANS.clear()


@contextmanager
def start_span(
    name: str,
    *,
    attributes: Mapping[str, Any] | None = None,
    trace_id: str | UUID | None = None,
) -> Iterator[SpanRecord]:
    """Start a span; never attaches full document content attributes."""
    safe_attrs = redact_mapping(dict(attributes or {}))
    for banned in ("content", "text", "body", "document_content", "prompt"):
        safe_attrs.pop(banned, None)
    resolved_trace = str(trace_id or new_id())
    span = SpanRecord(
        name=name,
        trace_id=resolved_trace,
        span_id=str(new_id()),
        attributes=safe_attrs,
    )
    bind_context(trace_id=resolved_trace, span=name)
    started = time.perf_counter()
    otel_cm = None
    otel_span = None
    if not _OTEL_CONFIGURED:
        configure_tracing()
    if _OTEL_TRACER is not None:
        try:
            otel_cm = _OTEL_TRACER.start_as_current_span(name)
            otel_span = otel_cm.__enter__()
            for key, value in safe_attrs.items():
                if isinstance(value, (str, int, float, bool)):
                    otel_span.set_attribute(key, value)
        except Exception as otel_exc:
            logger.debug("otel_span_start_failed", error=type(otel_exc).__name__)
            otel_cm = None
            otel_span = None
    try:
        yield span
    except Exception as exc:
        span.status = "error"
        span.error = type(exc).__name__
        if otel_span is not None:
            try:
                from opentelemetry.trace import Status, StatusCode

                otel_span.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception as status_exc:
                logger.debug("otel_status_failed", error=type(status_exc).__name__)
        raise
    finally:
        span.duration_ms = (time.perf_counter() - started) * 1000.0
        _SPANS.append(span)
        if otel_cm is not None:
            try:
                otel_cm.__exit__(None, None, None)
            except Exception as close_exc:
                logger.debug("otel_span_close_failed", error=type(close_exc).__name__)
        logger.debug(
            "span_finished",
            span_name=name,
            duration_ms=span.duration_ms,
            status=span.status,
        )


__all__ = [
    "SpanRecord",
    "clear_spans",
    "configure_tracing",
    "recorded_spans",
    "start_span",
]
