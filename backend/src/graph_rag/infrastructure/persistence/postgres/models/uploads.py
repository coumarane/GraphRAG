"""ORM model for upload sessions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from graph_rag.domain.ids import new_id
from graph_rag.infrastructure.persistence.postgres.base import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
)


class UploadSessionModel(Base, TimestampMixin, TenantOwnedMixin):
    """Short-lived intake row. A document exists only after acceptance."""

    __tablename__ = "upload_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "staging_object_key", name="uq_upload_sessions_staging_key"),
        UniqueConstraint("tenant_id", "final_object_key", name="uq_upload_sessions_final_key"),
        UniqueConstraint("ingestion_run_id", name="uq_upload_sessions_run"),
    )

    upload_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[UUID | None] = mapped_column(nullable=True)
    document_id: Mapped[UUID | None] = mapped_column(nullable=True)
    version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    staging_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    declared_byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(256), nullable=True)
    object_version_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingestion_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_reservation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    storage_reservation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
