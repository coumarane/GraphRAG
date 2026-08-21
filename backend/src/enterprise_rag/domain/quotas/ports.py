"""Quota service protocol."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from enterprise_rag.domain.quotas.models import QuotaMetric, QuotaPeriod, QuotaReservation


class QuotaService(Protocol):
    """Atomic quota reservation and settlement."""

    def reserve(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID | None,
        metric: QuotaMetric,
        quantity: int,
        period: QuotaPeriod | None = None,
    ) -> QuotaReservation:
        """Reserve capacity or raise QuotaExceededError."""
        ...

    def commit(
        self,
        *,
        reservation_id: UUID,
        actual_quantity: int,
    ) -> None:
        """Settle reservation to actual usage."""
        ...

    def release(self, *, reservation_id: UUID) -> None:
        """Release unused reservation without charging."""
        ...
