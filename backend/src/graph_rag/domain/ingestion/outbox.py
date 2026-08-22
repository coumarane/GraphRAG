"""Transactional outbox records for durable ingest enqueue."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.ids import deterministic_id, new_id
from graph_rag.domain.types import JsonValue

INGEST_QUEUED_EVENT = "ingest.queued"


def ingest_outbox_event_id(*, tenant_id: UUID, ingestion_run_id: UUID) -> UUID:
    """Stable outbox primary key so duplicate enqueue is an upsert."""
    return deterministic_id(
        "outbox",
        str(tenant_id),
        INGEST_QUEUED_EVENT,
        str(ingestion_run_id),
    )


class OutboxEventRecord(BaseModel):
    """Platform outbox row (not RLS-scoped; publisher reads all tenants)."""

    model_config = ConfigDict(extra="forbid")

    outbox_event_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    event_type: str = INGEST_QUEUED_EVENT
    aggregate_id: UUID
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    publish_attempts: int = 0
    last_error: str | None = None
    published_at: datetime | None = None
    stream_message_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
