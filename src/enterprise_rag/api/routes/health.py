"""Health and metrics routes."""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter

from enterprise_rag.api.dependencies import ContainerDep
from enterprise_rag.api.schemas import HealthResponse
from enterprise_rag.infrastructure.observability import get_metrics

router = APIRouter(tags=["operations"])


@router.get("/health/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=HealthResponse)
async def ready(container: ContainerDep) -> HealthResponse:
    for check in container.ready_checks:
        result = check()
        if inspect.isawaitable(result):
            result = await result
        if not result:
            from enterprise_rag.shared.exceptions import TransientError

            raise TransientError("Service not ready")
    return HealthResponse(status="ready")


@router.get("/metrics")
async def metrics(container: ContainerDep) -> dict[str, Any]:
    """JSON metrics snapshot for operators (Prometheus lives at GET /metrics)."""
    registry = get_metrics()
    snap = registry.snapshot()
    flat = dict(container.metrics)
    flat.update(registry.as_flat_counters())
    return {
        "requests_total": flat.get("requests_total", 0),
        "counters": snap["counters"],
        "gauges": snap["gauges"],
        "histograms": snap["histograms"],
        "flat": flat,
    }
