"""Task queue and dead-letter store protocols."""

from __future__ import annotations

from typing import Protocol

from enterprise_rag.domain.ingestion.retry import DeadLetterRecord, IngestionTaskMessage
from enterprise_rag.domain.tenant import TenantContext


class IngestionTaskQueue(Protocol):
    """Async work queue for ingestion runs."""

    async def enqueue(self, message: IngestionTaskMessage) -> None:
        """Enqueue a run for worker execution."""
        ...

    async def dequeue(self, *, timeout_seconds: float | None = None) -> IngestionTaskMessage | None:
        """Claim the next available task, or return None when empty/timeout."""
        ...

    async def acknowledge(self, task_id: object) -> None:
        """Mark a task as successfully processed."""
        ...

    async def depth(self) -> int:
        """Return approximate queue depth."""
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
