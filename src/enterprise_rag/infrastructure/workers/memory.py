"""In-memory task queue and dead-letter store for tests/local workers."""

from __future__ import annotations

import asyncio
from uuid import UUID

from enterprise_rag.domain.ingestion.retry import DeadLetterRecord, IngestionTaskMessage
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import AuthorizationError


class InMemoryIngestionTaskQueue:
    """FIFO asyncio queue for ingestion tasks."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[IngestionTaskMessage] = asyncio.Queue()
        self._inflight: dict[UUID, IngestionTaskMessage] = {}

    async def enqueue(self, message: IngestionTaskMessage) -> None:
        await self._queue.put(message)

    async def dequeue(self, *, timeout_seconds: float | None = None) -> IngestionTaskMessage | None:
        try:
            if timeout_seconds is None:
                message = await self._queue.get()
            else:
                message = await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None
        self._inflight[message.task_id] = message
        return message

    async def acknowledge(self, task_id: object) -> None:
        self._inflight.pop(UUID(str(task_id)), None)

    async def depth(self) -> int:
        return self._queue.qsize() + len(self._inflight)


class InMemoryDeadLetterStore:
    """Process-local dead-letter sink."""

    def __init__(self) -> None:
        self.records: list[DeadLetterRecord] = []

    async def append(self, tenant: TenantContext, record: DeadLetterRecord) -> DeadLetterRecord:
        if record.tenant_id != tenant.tenant_id:
            raise AuthorizationError("Dead-letter tenant mismatch")
        self.records.append(record)
        return record

    async def list_for_run(
        self,
        tenant: TenantContext,
        ingestion_run_id: object,
    ) -> list[DeadLetterRecord]:
        run_id = UUID(str(ingestion_run_id))
        return [
            record
            for record in self.records
            if record.tenant_id == tenant.tenant_id and record.ingestion_run_id == run_id
        ]
