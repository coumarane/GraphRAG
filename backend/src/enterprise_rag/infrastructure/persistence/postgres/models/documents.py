"""ORM models for tenants, documents and versions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.ingestion.stages import DocumentLifecycleStatus
from enterprise_rag.infrastructure.persistence.postgres.base import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
)


class TenantModel(Base, TimestampMixin):
    """Tenant registry (not tenant-owned; global)."""

    __tablename__ = "tenants"

    tenant_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=new_id,
    )
    tenant_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        nullable=False,
        default=dict,
    )


class DocumentModel(Base, TimestampMixin, TenantOwnedMixin):
    """Document aggregate root."""

    __tablename__ = "documents"

    document_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=DocumentLifecycleStatus.REGISTERED.value,
    )
    current_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    tags: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    security_labels: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_unit: Mapped[str | None] = mapped_column(String(128), nullable=True)
    classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    required_clearance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allowed_groups: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        nullable=False,
        default=dict,
    )


class DocumentVersionModel(Base, TimestampMixin, TenantOwnedMixin):
    """Immutable document version metadata."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "version_number",
            name="uq_document_versions_number",
        ),
    )

    version_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=DocumentLifecycleStatus.REGISTERED.value,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        nullable=False,
        default=dict,
    )
