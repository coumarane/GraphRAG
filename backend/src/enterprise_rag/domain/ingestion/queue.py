"""Task queue and dead-letter store protocols."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from enterprise_rag.domain.ingestion.retry import DeadLetterRecord, IngestionTaskMessage
from enterprise_rag.domain.tenant import TenantContext


@dataclass(frozen=True)
class PendingStreamEntry:
    """One Redis PEL (or in-memory equivalent) pending message."""

    stream_message_id: str
    consumer_name: str
    idle_ms: int
    delivery_count: int
    ingestion_run_id: UUID | None = None
    tenant_id: UUID | None = None


class IngestionTaskQueue(Protocol):
    """Async work queue for ingestion runs.

    Redis delivery is at-least-once. Callers must treat duplicate
    ``dequeue`` results as retries of the same durable job.
    """

    async def enqueue(self, message: IngestionTaskMessage) -> str | None:
        """Enqueue a run for worker execution. Returns stream id when known."""
        ...

    async def dequeue(self, *, timeout_seconds: float | None = None) -> IngestionTaskMessage | None:
        """Claim the next available task, or return None when empty/timeout."""
        ...

    async def acknowledge(self, task_id: object) -> None:
        """Remove a message from the pending list after a durable terminal state."""
        ...

    async def depth(self) -> int:
        """Return approximate queue depth (new + pending)."""
        ...


class StreamIngestionQueue(IngestionTaskQueue, Protocol):
    """Redis Streams consumer-group queue with reclaim and metrics."""

    async def pending_entries(self, *, idle_ms: int = 0) -> list[PendingStreamEntry]:
        """List PEL entries idle for at least ``idle_ms``."""
        ...

    async def claim(
        self,
        stream_message_id: str,
        *,
        min_idle_ms: int,
    ) -> IngestionTaskMessage | None:
        """XCLAIM one pending message when it has been idle long enough."""
        ...

    async def pending_count(self) -> int:
        """Return PEL size for this consumer group."""
        ...

    async def oldest_pending_age_seconds(self) -> float | None:
        """Age of the oldest PEL entry, or None when empty."""
        ...

    async def lookup_published(self, outbox_event_id: UUID) -> str | None:
        """Return a previously published stream id for duplicate-safe XADD."""
        ...

    async def has_message(self, stream_message_id: str) -> bool:
        """True when the stream still holds this message id."""
        ...


class DeadLetterStore(Protocol):
    """Persists exhausted ingestion failures for operator inspection."""

    async def append(self, tenant: TenantContext, record: DeadLetterRecord) -> DeadLetterRecord:
        """Store a dead-letter record."""
        ...

    async def list_for_run(
        self,
        tenant: TenantContext,
        ingestion_run_id: object,
    ) -> list[DeadLetterRecord]:
        """List dead letters for one ingestion run."""
        ...
