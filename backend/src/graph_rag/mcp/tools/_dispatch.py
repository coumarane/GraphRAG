"""Shared authz/quota plumbing for MCP tool handlers.

Application services are not uniformly authz/quota-blind: only
``RegisterSourceService`` self-enforces (see ``ingestion.py``). Every other
tool handler here must replicate its mirrored API route's
require_action -> quota reserve/commit/release -> service call -> commit_db
sequence explicitly, or it silently bypasses authorization/quotas that the
HTTP route would have enforced.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from graph_rag.application.authorization.gate import commit_quota, release_quota, reserve_quota
from graph_rag.domain.quotas.models import QuotaMetric, QuotaPeriod
from graph_rag.domain.tenant import TenantContext


@asynccontextmanager
async def quota_guard(
    quotas: Any,
    tenant: TenantContext,
    *,
    metric: QuotaMetric,
    quantity: int = 1,
    period: QuotaPeriod | None = QuotaPeriod.DAY,
) -> AsyncIterator[None]:
    """Reserve a quota unit, commit on success, release on failure."""
    reservation = await reserve_quota(
        quotas, tenant, metric=metric, quantity=quantity, period=period
    )
    try:
        yield
    except Exception:
        await release_quota(quotas, reservation_id=reservation.reservation_id)
        raise
    await commit_quota(
        quotas, reservation_id=reservation.reservation_id, actual_quantity=quantity
    )
