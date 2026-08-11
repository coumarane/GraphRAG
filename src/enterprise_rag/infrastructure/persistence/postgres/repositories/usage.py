"""SQLAlchemy usage event repository."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from enterprise_rag.application.usage.aggregate import aggregate_usage_events
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.domain.usage.models import UsageCapability, UsageEvent, UsageSummary
from enterprise_rag.infrastructure.persistence.postgres.models.usage import ModelUsageEventModel


class SqlAlchemyUsageRepository:
    """Postgres-backed usage ledger."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, event: UsageEvent) -> None:
        row = ModelUsageEventModel(
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            capability=event.capability.value
            if hasattr(event.capability, "value")
            else str(event.capability),
            provider=event.provider,
            model_name=event.model_name,
            role=event.role,
            prompt_tokens=event.prompt_tokens,
            completion_tokens=event.completion_tokens,
            total_tokens=event.total_tokens,
            estimated_usd=Decimal(str(event.estimated_usd)),
            known_pricing=event.known_pricing,
            correlation_id=event.correlation_id,
            document_id=event.document_id,
            ingestion_run_id=event.ingestion_run_id,
            query_id=event.query_id,
            latency_ms=event.latency_ms,
            created_at=event.created_at,
        )
        self._session.add(row)
        await self._session.flush()

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
        fetch_start = min(start_utc, month_utc)
        stmt: Select[tuple[ModelUsageEventModel]] = (
            select(ModelUsageEventModel)
            .where(ModelUsageEventModel.tenant_id == tenant.tenant_id)
            .where(ModelUsageEventModel.created_at >= fetch_start)
            .where(ModelUsageEventModel.created_at <= end_utc)
            .order_by(ModelUsageEventModel.created_at.asc())
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        events = [_to_domain(row) for row in rows]
        return aggregate_usage_events(
            events,
            from_date=start_utc.date(),
            to_date=end_utc.date(),
            month_start=month_utc.date(),
        )


def _to_domain(row: ModelUsageEventModel) -> UsageEvent:
    return UsageEvent(
        event_id=row.event_id,
        tenant_id=row.tenant_id,
        created_at=row.created_at,
        capability=UsageCapability(row.capability),
        provider=row.provider,
        model_name=row.model_name,
        role=row.role,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        total_tokens=row.total_tokens,
        estimated_usd=Decimal(str(row.estimated_usd)),
        known_pricing=bool(row.known_pricing),
        correlation_id=row.correlation_id,
        document_id=row.document_id,
        ingestion_run_id=row.ingestion_run_id,
        query_id=row.query_id,
        latency_ms=row.latency_ms,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
