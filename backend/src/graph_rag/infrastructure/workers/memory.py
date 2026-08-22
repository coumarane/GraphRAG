"""In-memory task queue for tests/local workers."""

from __future__ import annotations

import asyncio
import contextlib
from uuid import UUID

from graph_rag.domain.ingestion.retry import IngestionTaskMessage
from graph_rag.infrastructure.persistence.dead_letters import InMemoryDeadLetterStore

__all__ = ["InMemoryDeadLetterStore", "InMemoryIngestionTaskQueue"]


class InMemoryIngestionTaskQueue:
    """FIFO asyncio queue for ingestion tasks."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[IngestionTaskMessage] = asyncio.Queue()
        self._inflight: dict[UUID, IngestionTaskMessage] = {}

    async def enqueue(self, message: IngestionTaskMessage) -> str:
        await self._queue.put(message)
        return str(message.task_id)

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
        raw = str(task_id)
        with contextlib.suppress(ValueError):
            self._inflight.pop(UUID(raw), None)
        for inflight_id, message in list(self._inflight.items()):
            if raw in {str(message.task_id), str(message.stream_message_id or "")}:
                self._inflight.pop(inflight_id, None)

    async def depth(self) -> int:
        return self._queue.qsize() + len(self._inflight)
