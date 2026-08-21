"""ORM models for ingestion runs, stages and parser attempts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.ingestion.stages import IngestionRunStatus, StageStatus
from enterprise_rag.infrastructure.persistence.postgres.base import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
)


class IngestionRunModel(Base, TimestampMixin, TenantOwnedMixin):
    """Ingestion run lifecycle row."""

    __tablename__ = "ingestion_runs"

    ingestion_run_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
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
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=IngestionRunStatus.PENDING.value,
    )
    parser_requested: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pages_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elements_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        nullable=False,
        default=dict,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionStageModel(Base, TimestampMixin, TenantOwnedMixin):
    """Per-stage status row for an ingestion run."""

    __tablename__ = "ingestion_stages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "ingestion_run_id",
            "stage",
            name="uq_ingestion_stages_run_stage",
        ),
    )

    stage_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=StageStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        nullable=False,
        default=dict,
    )


class ParserAttemptModel(Base, TimestampMixin, TenantOwnedMixin):
    """Parser attempt audit row."""

    __tablename__ = "parser_attempts"

    attempt_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parser_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    warnings: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        nullable=False,
        default=dict,
    )
