"""Ingestion run/stage repository adapter."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enterprise_rag.domain.ingestion.records import (
    IngestionRunRecord,
    IngestionStageRecord,
    ParserAttemptRecord,
)
from enterprise_rag.domain.ingestion.stages import INGESTION_STAGE_ORDER, IngestionStageName
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.persistence.postgres.mappers import (
    parser_attempt_to_record,
    run_to_record,
    stage_to_record,
)
from enterprise_rag.infrastructure.persistence.postgres.models import (
    IngestionRunModel,
    IngestionStageModel,
    ParserAttemptModel,
)
from enterprise_rag.infrastructure.persistence.postgres.rls import (
    require_matching_tenant,
    set_tenant_context,
)
from enterprise_rag.shared.exceptions import NotFoundError


class SqlAlchemyIngestionRepository:
    """SQLAlchemy implementation of ``IngestionRepository``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(
        self,
        tenant: TenantContext,
        run: IngestionRunRecord,
        stages: list[IngestionStageRecord],
    ) -> IngestionRunRecord:
        require_matching_tenant(tenant, run.tenant_id)
        await set_tenant_context(self._session, tenant)
        model = IngestionRunModel(
            ingestion_run_id=run.ingestion_run_id,
            tenant_id=run.tenant_id,
            document_id=run.document_id,
            version_id=run.version_id,
            status=run.status.value,
            parser_requested=run.parser_requested,
            parser_used=run.parser_used,
            config_fingerprint=run.config_fingerprint,
            content_hash=run.content_hash,
            pages_processed=run.pages_processed,
            elements_processed=run.elements_processed,
            retry_count=run.retry_count,
            latest_warning=run.latest_warning,
            error_code=run.error_code,
            error_message=run.error_message,
            correlation_id=run.correlation_id,
            worker_id=run.worker_id,
            heartbeat_at=run.heartbeat_at,
            metadata_json=dict(run.metadata),
            started_at=run.started_at,
            completed_at=run.completed_at,
        )
        self._session.add(model)
        for stage in stages:
            require_matching_tenant(tenant, stage.tenant_id)
            self._session.add(
                IngestionStageModel(
                    stage_id=stage.stage_id,
                    tenant_id=stage.tenant_id,
                    ingestion_run_id=run.ingestion_run_id,
                    stage=stage.stage.value,
                    status=stage.status.value,
                    attempt_count=stage.attempt_count,
                    idempotency_key=stage.idempotency_key,
                    config_fingerprint=stage.config_fingerprint,
                    warning=stage.warning,
                    error_code=stage.error_code,
                    error_message=stage.error_message,
                    worker_id=stage.worker_id,
                    heartbeat_at=stage.heartbeat_at,
                    started_at=stage.started_at,
                    completed_at=stage.completed_at,
                    metadata_json=dict(stage.metadata),
                )
            )
        await self._session.flush()
        return run_to_record(model)

    async def get_run(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
    ) -> IngestionRunRecord | None:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(IngestionRunModel).where(
                IngestionRunModel.ingestion_run_id == ingestion_run_id,
                IngestionRunModel.tenant_id == tenant.tenant_id,
            )
        )
        model = result.scalar_one_or_none()
        return run_to_record(model) if model is not None else None

    async def update_run(
        self,
        tenant: TenantContext,
        run: IngestionRunRecord,
    ) -> IngestionRunRecord:
        require_matching_tenant(tenant, run.tenant_id)
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(IngestionRunModel).where(
                IngestionRunModel.ingestion_run_id == run.ingestion_run_id,
                IngestionRunModel.tenant_id == tenant.tenant_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError(
                "Ingestion run not found",
                details={"ingestion_run_id": str(run.ingestion_run_id)},
            )
        model.status = run.status.value
        model.parser_requested = run.parser_requested
        model.parser_used = run.parser_used
        model.config_fingerprint = run.config_fingerprint
        model.content_hash = run.content_hash
        model.pages_processed = run.pages_processed
        model.elements_processed = run.elements_processed
        model.retry_count = run.retry_count
        model.latest_warning = run.latest_warning
        model.error_code = run.error_code
        model.error_message = run.error_message
        model.correlation_id = run.correlation_id
        model.worker_id = run.worker_id
        model.heartbeat_at = run.heartbeat_at
        model.metadata_json = dict(run.metadata)
        model.started_at = run.started_at
        model.completed_at = run.completed_at
        await self._session.flush()
        return run_to_record(model)

    async def list_stages(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
    ) -> list[IngestionStageRecord]:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(IngestionStageModel).where(
                IngestionStageModel.ingestion_run_id == ingestion_run_id,
                IngestionStageModel.tenant_id == tenant.tenant_id,
            )
        )
        models = list(result.scalars().all())
        order = {name.value: index for index, name in enumerate(INGESTION_STAGE_ORDER)}
        models.sort(key=lambda item: order.get(item.stage, 10_000))
        return [stage_to_record(model) for model in models]

    async def get_stage(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
        stage: IngestionStageName,
    ) -> IngestionStageRecord | None:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(IngestionStageModel).where(
                IngestionStageModel.ingestion_run_id == ingestion_run_id,
                IngestionStageModel.tenant_id == tenant.tenant_id,
                IngestionStageModel.stage == stage.value,
            )
        )
        model = result.scalar_one_or_none()
        return stage_to_record(model) if model is not None else None

    async def update_stage(
        self,
        tenant: TenantContext,
        stage: IngestionStageRecord,
    ) -> IngestionStageRecord:
        require_matching_tenant(tenant, stage.tenant_id)
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(IngestionStageModel).where(
                IngestionStageModel.stage_id == stage.stage_id,
                IngestionStageModel.tenant_id == tenant.tenant_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError(
                "Ingestion stage not found",
                details={"stage_id": str(stage.stage_id)},
            )
        model.status = stage.status.value
        model.attempt_count = stage.attempt_count
        model.idempotency_key = stage.idempotency_key
        model.config_fingerprint = stage.config_fingerprint
        model.warning = stage.warning
        model.error_code = stage.error_code
        model.error_message = stage.error_message
        model.worker_id = stage.worker_id
        model.heartbeat_at = stage.heartbeat_at
        model.started_at = stage.started_at
        model.completed_at = stage.completed_at
        model.metadata_json = dict(stage.metadata)
        await self._session.flush()
        return stage_to_record(model)

    async def add_parser_attempt(
        self,
        tenant: TenantContext,
        attempt: ParserAttemptRecord,
    ) -> ParserAttemptRecord:
        require_matching_tenant(tenant, attempt.tenant_id)
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(ParserAttemptModel).where(
                ParserAttemptModel.attempt_id == attempt.attempt_id,
                ParserAttemptModel.tenant_id == tenant.tenant_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            model = ParserAttemptModel(
                attempt_id=attempt.attempt_id,
                tenant_id=attempt.tenant_id,
                ingestion_run_id=attempt.ingestion_run_id,
                parser_name=attempt.parser_name,
                parser_version=attempt.parser_version,
                success=attempt.success,
                duration_ms=attempt.duration_ms,
                failure_category=attempt.failure_category,
                warnings=list(attempt.warnings),
                metadata_json=dict(attempt.metadata),
            )
            self._session.add(model)
        else:
            model.parser_name = attempt.parser_name
            model.parser_version = attempt.parser_version
            model.success = attempt.success
            model.duration_ms = attempt.duration_ms
            model.failure_category = attempt.failure_category
            model.warnings = list(attempt.warnings)
            model.metadata_json = dict(attempt.metadata)
        await self._session.flush()
        return parser_attempt_to_record(model)

    async def list_parser_attempts(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
    ) -> list[ParserAttemptRecord]:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(ParserAttemptModel)
            .where(
                ParserAttemptModel.ingestion_run_id == ingestion_run_id,
                ParserAttemptModel.tenant_id == tenant.tenant_id,
            )
            .order_by(ParserAttemptModel.created_at.asc())
        )
        return [parser_attempt_to_record(model) for model in result.scalars().all()]
