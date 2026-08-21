"""In-memory usage ledger for tests and local runtime."""

from __future__ import annotations

from datetime import UTC, datetime

from enterprise_rag.application.usage.aggregate import aggregate_usage_events
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.domain.usage.models import UsageEvent, UsageSummary


class InMemoryUsageRepository:
    """Process-local usage event store."""

    def __init__(self) -> None:
        self._events: list[UsageEvent] = []

    @property
    def events(self) -> list[UsageEvent]:
        return list(self._events)

    async def record(self, event: UsageEvent) -> None:
        self._events.append(event.model_copy(deep=True))

    async def summarize(
        self,
        tenant: TenantContext,
        *,
        start: datetime,
        end: datetime,
        month_start: datetime,
    ) -> UsageSummary:
        tenant.ensure_authorized()
        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        month_utc = _ensure_utc(month_start)
        scoped = [
            event
            for event in self._events
            if event.tenant_id == tenant.tenant_id
            and start_utc <= _ensure_utc(event.created_at) <= end_utc
        ]
        # Month spend may include days before `start` in the same calendar month.
        month_events = [
            event
            for event in self._events
            if event.tenant_id == tenant.tenant_id
            and _ensure_utc(event.created_at) >= month_utc
            and _ensure_utc(event.created_at) <= end_utc
        ]
        # Reuse aggregator with combined set so month_spend is correct.
        combined_ids = {event.event_id for event in scoped}
        combined = list(scoped)
        for event in month_events:
            if event.event_id not in combined_ids:
                combined.append(event)
        return aggregate_usage_events(
            combined,
            from_date=start_utc.date(),
            to_date=end_utc.date(),
            month_start=month_utc.date(),
        )

    def clear(self) -> None:
        self._events.clear()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
