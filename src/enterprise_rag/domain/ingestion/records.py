"""Persistence-facing domain records for document lifecycle."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.domain.ingestion.stages import (
    DocumentLifecycleStatus,
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
)
from enterprise_rag.domain.types import JsonValue


class TenantRecord(BaseModel):
    """Persisted tenant."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    tenant_key: str
    display_name: str | None = None
    is_active: bool = True
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentRecord(BaseModel):
    """Persisted document aggregate root."""

    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    tenant_id: UUID
    title: str | None = None
    document_type: str | None = None
    status: DocumentLifecycleStatus = DocumentLifecycleStatus.REGISTERED
    current_version_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)
    security_labels: list[str] = Field(default_factory=list)
    owner_user_id: UUID | None = None
    department: str | None = None
    country: str | None = None
    business_unit: str | None = None
    classification: str | None = None
    required_clearance: int | None = None
    allowed_groups: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentVersionRecord(BaseModel):
    """Persisted immutable document version."""

    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_number: int = Field(ge=1)
    source_filename: str
    mime_type: str
    content_hash: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    page_count: int | None = Field(default=None, ge=0)
    original_object_key: str | None = None
    status: DocumentLifecycleStatus = DocumentLifecycleStatus.REGISTERED
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class IngestionRunRecord(BaseModel):
    """Persisted ingestion run."""

    model_config = ConfigDict(extra="forbid")

    ingestion_run_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    status: IngestionRunStatus = IngestionRunStatus.PENDING
    parser_requested: str | None = None
    parser_used: str | None = None
    config_fingerprint: str | None = None
    content_hash: str | None = None
    pages_processed: int = 0
    elements_processed: int = 0
    retry_count: int = 0
    latest_warning: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    correlation_id: str | None = None
    worker_id: str | None = None
    heartbeat_at: datetime | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class IngestionStageRecord(BaseModel):
    """Persisted stage within an ingestion run."""

    model_config = ConfigDict(extra="forbid")

    stage_id: UUID
    tenant_id: UUID
    ingestion_run_id: UUID
    stage: IngestionStageName
    status: StageStatus = StageStatus.PENDING
    attempt_count: int = 0
    idempotency_key: str | None = None
    config_fingerprint: str | None = None
    warning: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    worker_id: str | None = None
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ParserAttemptRecord(BaseModel):
    """Record of a parser attempt for audit and fallback."""

    model_config = ConfigDict(extra="forbid")

    attempt_id: UUID
    tenant_id: UUID
    ingestion_run_id: UUID
    parser_name: str
    parser_version: str | None = None
    success: bool
    duration_ms: float | None = Field(default=None, ge=0.0)
    failure_category: str | None = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime | None = None
