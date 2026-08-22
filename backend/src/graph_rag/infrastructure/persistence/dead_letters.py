"""Dead-letter persistence adapters."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graph_rag.domain.ingestion.retry import DeadLetterRecord
from graph_rag.domain.ingestion.stages import IngestionStageName
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.postgres.models.outbox import (
    IngestionDeadLetterModel,
)
from graph_rag.infrastructure.persistence.postgres.rls import (
    require_matching_tenant,
    set_tenant_context,
)
from graph_rag.shared.exceptions import AuthorizationError


def _to_record(model: IngestionDeadLetterModel) -> DeadLetterRecord:
    return DeadLetterRecord(
        dead_letter_id=model.dead_letter_id,
        tenant_id=model.tenant_id,
        ingestion_run_id=model.ingestion_run_id,
        stage=IngestionStageName(model.stage),
        attempt_count=model.attempt_count,
        error_code=model.error_code,
        error_message=model.error_message,
        original_stream_id=model.original_stream_id,
        correlation_id=model.correlation_id,
        payload=dict(model.payload or {}),
        created_at=model.created_at,
    )


class SqlAlchemyDeadLetterStore:
    """Postgres dead-letter store (RLS tenant isolation)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, tenant: TenantContext, record: DeadLetterRecord) -> DeadLetterRecord:
        require_matching_tenant(tenant, record.tenant_id)
        await set_tenant_context(self._session, tenant)
        existing = await self._session.execute(
            select(IngestionDeadLetterModel).where(
                IngestionDeadLetterModel.dead_letter_id == record.dead_letter_id,
                IngestionDeadLetterModel.tenant_id == tenant.tenant_id,
            )
        )
        model = existing.scalar_one_or_none()
        if model is None:
            model = IngestionDeadLetterModel(
                dead_letter_id=record.dead_letter_id,
                tenant_id=record.tenant_id,
                ingestion_run_id=record.ingestion_run_id,
                stage=record.stage.value,
                attempt_count=record.attempt_count,
                error_code=record.error_code,
                error_message=record.error_message,
                original_stream_id=record.original_stream_id,
                correlation_id=record.correlation_id,
                payload=dict(record.payload),
            )
            self._session.add(model)
        await self._session.flush()
        return _to_record(model)

    async def list_for_run(
        self,
        tenant: TenantContext,
        ingestion_run_id: object,
    ) -> list[DeadLetterRecord]:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        run_id = UUID(str(ingestion_run_id))
        result = await self._session.execute(
            select(IngestionDeadLetterModel)
            .where(
                IngestionDeadLetterModel.ingestion_run_id == run_id,
                IngestionDeadLetterModel.tenant_id == tenant.tenant_id,
            )
            .order_by(IngestionDeadLetterModel.created_at.asc())
        )
        return [_to_record(model) for model in result.scalars().all()]


class InMemoryDeadLetterStore:
    """Process-local dead-letter sink."""

    def __init__(self) -> None:
        self.records: list[DeadLetterRecord] = []

    async def append(self, tenant: TenantContext, record: DeadLetterRecord) -> DeadLetterRecord:
        if record.tenant_id != tenant.tenant_id:
            raise AuthorizationError("Dead-letter tenant mismatch")
        for index, existing in enumerate(self.records):
            if existing.dead_letter_id == record.dead_letter_id:
                self.records[index] = record
                return record
        self.records.append(record)
        return record

    async def list_for_run(
        self,
        tenant: TenantContext,
        ingestion_run_id: object,
    ) -> list[DeadLetterRecord]:
        run_id = UUID(str(ingestion_run_id))
        return [
            record
            for record in self.records
            if record.tenant_id == tenant.tenant_id and record.ingestion_run_id == run_id
        ]
