"""Usage metering repository protocol."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.domain.usage.models import UsageEvent, UsageSummary


class UsageRepository(Protocol):
    """Durable ledger for model usage events."""

    async def record(self, event: UsageEvent) -> None:
        """Append one usage event."""

    async def summarize(
        self,
        tenant: TenantContext,
        *,
        start: datetime,
        end: datetime,
        month_start: datetime,
    ) -> UsageSummary:
        """Aggregate spend/tokens/requests for the dashboard."""


class UsageRecorder(Protocol):
    """Fire-and-forget recorder used by model adapters."""

    async def record(self, event: UsageEvent) -> None:
        """Persist a usage event (best-effort)."""
