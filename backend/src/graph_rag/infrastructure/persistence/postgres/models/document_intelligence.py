"""ORM models for Document Intelligence models, fields, extraction runs and fields.

Extracted fields are real columns, not one JSONB blob per run -- the source
request (``docs/document-intelligent-feature.md``) explicitly requires
extracted values to be individually searchable/auditable/filterable, which
plain columns support far better than per-field GIN expression indexes on a
blob would.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from graph_rag.domain.ids import new_id
from graph_rag.infrastructure.persistence.postgres.base import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
)

_JSON_ANY = JSON().with_variant(JSONB(), "postgresql")


class DocumentIntelligenceModelModel(Base, TimestampMixin, TenantOwnedMixin):
    """A registered extraction "model" (prebuilt, custom, or ad-hoc metadata)."""

    __tablename__ = "document_intelligence_models"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "model_key",
            "version",
            name="uq_document_intelligence_models_tenant_key_version",
        ),
    )

    model_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    model_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_type: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="internal")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        nullable=False,
        default=dict,
    )


class DocumentIntelligenceModelFieldModel(Base, TimestampMixin, TenantOwnedMixin):
    """One field in a model's schema."""

    __tablename__ = "document_intelligence_model_fields"

    field_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    model_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_intelligence_models.model_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str] = mapped_column(String(32), nullable=False)
    default_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DocumentExtractionRunModel(Base, TimestampMixin, TenantOwnedMixin):
    """One extraction attempt against one document version."""

    __tablename__ = "document_extraction_runs"

    run_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.version_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ingestion_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_intelligence_models.model_id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="internal")
    plugin_version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.0.0")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    selected_fields_json: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentExtractedFieldModel(Base, TimestampMixin, TenantOwnedMixin):
    """One extracted field value, with full provenance."""

    __tablename__ = "document_extracted_fields"
    __table_args__ = (
        UniqueConstraint("run_id", "name", name="uq_document_extracted_fields_run_name"),
    )

    extracted_field_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_extraction_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    value_json: Mapped[Any] = mapped_column(_JSON_ANY, nullable=False)
    normalized_value_json: Mapped[Any | None] = mapped_column(_JSON_ANY, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence_band: Mapped[str] = mapped_column(String(8), nullable=False, default="LOW")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    bounding_box_json: Mapped[Any | None] = mapped_column(_JSON_ANY, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
