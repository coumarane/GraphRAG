"""FastAPI middleware for correlation, tenant and request metrics."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from graph_rag.domain.ids import new_id
from graph_rag.infrastructure.observability.metrics import get_metrics
from graph_rag.shared.logging import bind_context, clear_context, get_logger

logger = get_logger(__name__)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Bind correlation/tenant context and record request latency metrics."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or str(new_id())
        tenant_key = request.headers.get("X-Tenant-Key")
        tenant_id_header = request.headers.get("X-Tenant-ID")
        bind_context(
            correlation_id=correlation_id,
            path=request.url.path,
            method=request.method,
            tenant_key=tenant_key,
            tenant_id=tenant_id_header,
        )
        metrics = get_metrics()
        metrics.incr("http_requests_total", labels={"method": request.method})
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            duration = time.perf_counter() - started
            metrics.observe(
                "http_request_duration_seconds",
                duration,
                labels={"method": request.method},
            )
            metrics.incr(
                "http_responses_total",
                labels={"status": str(status_code)},
            )
            container = getattr(request.app.state, "container", None)
            if container is not None and hasattr(container, "metrics"):
                container.metrics["requests_total"] = int(
                    container.metrics.get("requests_total", 0)
                ) + 1
            logger.info(
                "http_request",
                status_code=status_code,
                duration_ms=round(duration * 1000, 2),
            )
            clear_context()


def parse_optional_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def request_observability_state(request: Request) -> dict[str, Any]:
    return {
        "correlation_id": request.headers.get("X-Correlation-ID"),
        "tenant_id": request.headers.get("X-Tenant-ID"),
        "tenant_key": request.headers.get("X-Tenant-Key"),
    }


__all__ = ["ObservabilityMiddleware", "parse_optional_uuid", "request_observability_state"]
