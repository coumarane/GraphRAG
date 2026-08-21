"""ORM models for the ingest outbox and dead-letter tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from enterprise_rag.domain.ids import new_id
from enterprise_rag.infrastructure.persistence.postgres.base import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
)


class OutboxEventModel(Base, TimestampMixin):
    """Cross-tenant outbox. Publisher must see unpublished rows without RLS."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "event_type",
            "aggregate_id",
            name="uq_outbox_events_tenant_type_aggregate",
        ),
    )

    outbox_event_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stream_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class IngestionDeadLetterModel(Base, TimestampMixin, TenantOwnedMixin):
    """Persisted exhausted ingest failures for operator inspection."""

    __tablename__ = "ingestion_dead_letters"

    dead_letter_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str] = mapped_column(String(128), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    original_stream_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
