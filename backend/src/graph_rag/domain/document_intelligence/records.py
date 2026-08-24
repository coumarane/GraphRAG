"""Persistence-facing domain records for Document Intelligence models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.types import JsonValue


class DocumentIntelligenceModelFieldRecord(BaseModel):
    """One field in a custom Document Intelligence model's schema."""

    model_config = ConfigDict(extra="forbid")

    field_id: UUID
    model_id: UUID
    tenant_id: UUID
    name: str
    label: str
    field_type: str
    default_selected: bool = False
    promote_to_document_metadata: bool = False
    sort_order: int = 0


class DocumentIntelligenceModelRecord(BaseModel):
    """Persisted custom Document Intelligence model (a saved field schema)."""

    model_config = ConfigDict(extra="forbid")

    model_id: UUID
    tenant_id: UUID
    model_key: str
    name: str
    model_type: str = "custom"
    version: str = "1.0"
    provider: str = "internal"
    is_builtin: bool = False
    created_by_user_id: UUID | None = None
    field_entity_mappings: dict[str, dict[str, str]] = Field(default_factory=dict)
    fields: list[DocumentIntelligenceModelFieldRecord] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentExtractionRunRecord(BaseModel):
    """One extraction attempt against one document version."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    ingestion_run_id: UUID | None = None
    model_id: UUID | None = None
    model_key: str | None = None
    provider: str = "internal"
    plugin_version: str = "0.0.0"
    status: str = "pending"
    fingerprint: str | None = None
    selected_fields: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentExtractedFieldRecord(BaseModel):
    """One extracted field value, with full provenance."""

    model_config = ConfigDict(extra="forbid")

    extracted_field_id: UUID
    tenant_id: UUID
    run_id: UUID
    name: str
    value: JsonValue
    normalized_value: JsonValue | None = None
    confidence: float = 0.0
    confidence_band: str = "LOW"
    page: int | None = None
    source_text: str | None = None
    bounding_box: dict[str, JsonValue] | None = None
    extraction_method: str
    model_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
