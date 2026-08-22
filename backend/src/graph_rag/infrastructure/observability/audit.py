"""Audit trail for model usage, retrieval decisions and citation mappings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.ids import new_id
from graph_rag.domain.types import JsonValue


class AuditEvent(BaseModel):
    """Persisted observability/audit event with retention metadata."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    event_type: str
    document_id: UUID | None = None
    version_id: UUID | None = None
    ingestion_run_id: UUID | None = None
    correlation_id: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retain_until: datetime | None = None


class AuditStore(Protocol):
    async def append(self, event: AuditEvent) -> AuditEvent: ...

    async def list_for_tenant(
        self,
        tenant_id: UUID,
        *,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]: ...


class InMemoryAuditStore:
    """Process-local audit store for unit tests and local containers."""

    def __init__(self, *, retention_days: int = 30) -> None:
        self.retention_days = retention_days
        self.events: list[AuditEvent] = []

    async def append(self, event: AuditEvent) -> AuditEvent:
        if event.retain_until is None:
            from datetime import timedelta

            event = event.model_copy(
                update={"retain_until": event.created_at + timedelta(days=self.retention_days)}
            )
        self.events.append(event)
        return event

    async def list_for_tenant(
        self,
        tenant_id: UUID,
        *,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        matched = [
            event
            for event in self.events
            if event.tenant_id == tenant_id
            and (event_type is None or event.event_type == event_type)
        ]
        return matched[-limit:]


__all__ = ["AuditEvent", "AuditStore", "InMemoryAuditStore"]
