"""Map between ORM models and domain records."""

from __future__ import annotations

from enterprise_rag.domain.ingestion.records import (
    DocumentRecord,
    DocumentVersionRecord,
    IngestionRunRecord,
    IngestionStageRecord,
    ParserAttemptRecord,
    TenantRecord,
)
from enterprise_rag.domain.ingestion.stages import (
    DocumentLifecycleStatus,
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
)
from enterprise_rag.domain.types import JsonValue
from enterprise_rag.infrastructure.persistence.postgres.models import (
    DocumentModel,
    DocumentVersionModel,
    IngestionRunModel,
    IngestionStageModel,
    ParserAttemptModel,
    TenantModel,
)


def _metadata(value: dict[str, object] | None) -> dict[str, JsonValue]:
    return dict(value or {})  # type: ignore[arg-type]


def tenant_to_record(model: TenantModel) -> TenantRecord:
    return TenantRecord(
        tenant_id=model.tenant_id,
        tenant_key=model.tenant_key,
        display_name=model.display_name,
        is_active=model.is_active,
        metadata=_metadata(model.metadata_json),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def document_to_record(model: DocumentModel) -> DocumentRecord:
    return DocumentRecord(
        document_id=model.document_id,
        tenant_id=model.tenant_id,
        title=model.title,
        document_type=model.document_type,
        status=DocumentLifecycleStatus(model.status),
        current_version_id=model.current_version_id,
        tags=[str(tag) for tag in (model.tags or [])],
        security_labels=[str(label) for label in (model.security_labels or [])],
        owner_user_id=model.owner_user_id,
        department=model.department,
        country=model.country,
        business_unit=model.business_unit,
        classification=model.classification,
        required_clearance=model.required_clearance,
        allowed_groups=[str(g) for g in (model.allowed_groups or [])],
        metadata=_metadata(model.metadata_json),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def version_to_record(model: DocumentVersionModel) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        version_id=model.version_id,
        tenant_id=model.tenant_id,
        document_id=model.document_id,
        version_number=model.version_number,
        source_filename=model.source_filename,
        mime_type=model.mime_type,
        content_hash=model.content_hash,
        byte_size=model.byte_size,
        page_count=model.page_count,
        original_object_key=model.original_object_key,
        status=DocumentLifecycleStatus(model.status),
        metadata=_metadata(model.metadata_json),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def run_to_record(model: IngestionRunModel) -> IngestionRunRecord:
    return IngestionRunRecord(
        ingestion_run_id=model.ingestion_run_id,
        tenant_id=model.tenant_id,
        document_id=model.document_id,
        version_id=model.version_id,
        status=IngestionRunStatus(model.status),
        parser_requested=model.parser_requested,
        parser_used=model.parser_used,
        config_fingerprint=model.config_fingerprint,
        content_hash=model.content_hash,
        pages_processed=model.pages_processed,
        elements_processed=model.elements_processed,
        retry_count=model.retry_count,
        latest_warning=model.latest_warning,
        error_code=model.error_code,
        error_message=model.error_message,
        correlation_id=model.correlation_id,
        worker_id=model.worker_id,
        heartbeat_at=model.heartbeat_at,
        metadata=_metadata(model.metadata_json),
        started_at=model.started_at,
        completed_at=model.completed_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def stage_to_record(model: IngestionStageModel) -> IngestionStageRecord:
    return IngestionStageRecord(
        stage_id=model.stage_id,
        tenant_id=model.tenant_id,
        ingestion_run_id=model.ingestion_run_id,
        stage=IngestionStageName(model.stage),
        status=StageStatus(model.status),
        attempt_count=model.attempt_count,
        idempotency_key=model.idempotency_key,
        config_fingerprint=model.config_fingerprint,
        warning=model.warning,
        error_code=model.error_code,
        error_message=model.error_message,
        worker_id=model.worker_id,
        heartbeat_at=model.heartbeat_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
        metadata=_metadata(model.metadata_json),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def parser_attempt_to_record(model: ParserAttemptModel) -> ParserAttemptRecord:
    return ParserAttemptRecord(
        attempt_id=model.attempt_id,
        tenant_id=model.tenant_id,
        ingestion_run_id=model.ingestion_run_id,
        parser_name=model.parser_name,
        parser_version=model.parser_version,
        success=model.success,
        duration_ms=model.duration_ms,
        failure_category=model.failure_category,
        warnings=[str(item) for item in (model.warnings or [])],
        metadata=_metadata(model.metadata_json),
        created_at=model.created_at,
    )
