"""In-memory Redis Streams analogue with consumer groups and a PEL."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from uuid import UUID

from enterprise_rag.domain.ingestion.queue import PendingStreamEntry
from enterprise_rag.domain.ingestion.retry import IngestionTaskMessage


def _next_stream_id(seq: int) -> str:
    millis = int(time.time() * 1000)
    return f"{millis}-{seq}"


@dataclass
class _StreamEntry:
    message_id: str
    message: IngestionTaskMessage
    created_ms: float
    acked: bool = False


@dataclass
class _Pending:
    message_id: str
    consumer_name: str
    last_delivered_ms: float
    delivery_count: int = 1


@dataclass
class InMemoryStreamIngestionQueue:
    """Consumer-group queue used by tests and local mode without Redis."""

    stream_key: str = "ingestion-jobs"
    group_name: str = "ingestion-workers"
    consumer_name: str = "worker-1"
    _entries: dict[str, _StreamEntry] = field(default_factory=dict)
    _order: list[str] = field(default_factory=list)
    _pending: dict[str, _Pending] = field(default_factory=dict)
    _dedupe: dict[UUID, str] = field(default_factory=dict)
    _seq: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _now_ms: float | None = None

    def _clock_ms(self) -> float:
        return self._now_ms if self._now_ms is not None else time.time() * 1000.0

    def advance_clock_ms(self, delta_ms: float) -> None:
        """Test helper to age PEL entries without sleeping."""
        self._now_ms = self._clock_ms() + delta_ms

    def simulate_restart(self) -> None:
        """Drop the stream and dedupe keys (Redis restart without persistence)."""
        self._entries.clear()
        self._order.clear()
        self._pending.clear()
        self._dedupe.clear()

    async def enqueue(self, message: IngestionTaskMessage) -> str:
        async with self._lock:
            if message.outbox_event_id is not None:
                existing = self._dedupe.get(message.outbox_event_id)
                if (
                    existing is not None
                    and existing in self._entries
                    and not self._entries[existing].acked
                ):
                    message.stream_message_id = existing
                    return existing
            self._seq += 1
            message_id = _next_stream_id(self._seq)
            cloned = message.model_copy(update={"stream_message_id": message_id})
            self._entries[message_id] = _StreamEntry(
                message_id=message_id,
                message=cloned,
                created_ms=self._clock_ms(),
            )
            self._order.append(message_id)
            if message.outbox_event_id is not None:
                self._dedupe[message.outbox_event_id] = message_id
            return message_id

    async def dequeue(self, *, timeout_seconds: float | None = None) -> IngestionTaskMessage | None:
        _ = timeout_seconds
        async with self._lock:
            for message_id in self._order:
                entry = self._entries[message_id]
                if entry.acked or message_id in self._pending:
                    continue
                now = self._clock_ms()
                self._pending[message_id] = _Pending(
                    message_id=message_id,
                    consumer_name=self.consumer_name,
                    last_delivered_ms=now,
                    delivery_count=1,
                )
                msg = entry.message.model_copy(update={"stream_message_id": message_id})
                msg.attempt_count = entry.message.attempt_count
                return msg
            return None

    async def acknowledge(self, task_id: object) -> None:
        message_id = str(task_id)
        async with self._lock:
            self._pending.pop(message_id, None)
            entry = self._entries.get(message_id)
            if entry is not None:
                entry.acked = True

    async def depth(self) -> int:
        async with self._lock:
            waiting = sum(
                1
                for message_id in self._order
                if not self._entries[message_id].acked and message_id not in self._pending
            )
            return waiting + len(self._pending)

    async def pending_entries(self, *, idle_ms: int = 0) -> list[PendingStreamEntry]:
        now = self._clock_ms()
        async with self._lock:
            rows: list[PendingStreamEntry] = []
            for pending in self._pending.values():
                idle = int(now - pending.last_delivered_ms)
                if idle < idle_ms:
                    continue
                entry = self._entries.get(pending.message_id)
                message = entry.message if entry is not None else None
                rows.append(
                    PendingStreamEntry(
                        stream_message_id=pending.message_id,
                        consumer_name=pending.consumer_name,
                        idle_ms=idle,
                        delivery_count=pending.delivery_count,
                        ingestion_run_id=message.ingestion_run_id if message else None,
                        tenant_id=message.tenant_id if message else None,
                    )
                )
            return rows

    async def claim(
        self,
        stream_message_id: str,
        *,
        min_idle_ms: int,
    ) -> IngestionTaskMessage | None:
        now = self._clock_ms()
        async with self._lock:
            pending = self._pending.get(stream_message_id)
            entry = self._entries.get(stream_message_id)
            if pending is None or entry is None or entry.acked:
                return None
            idle = int(now - pending.last_delivered_ms)
            if idle < min_idle_ms:
                return None
            pending.consumer_name = self.consumer_name
            pending.last_delivered_ms = now
            pending.delivery_count += 1
            msg = entry.message.model_copy(update={"stream_message_id": stream_message_id})
            msg.attempt_count = pending.delivery_count
            return msg

    async def pending_count(self) -> int:
        async with self._lock:
            return len(self._pending)

    async def oldest_pending_age_seconds(self) -> float | None:
        now = self._clock_ms()
        async with self._lock:
            if not self._pending:
                return None
            oldest = min(item.last_delivered_ms for item in self._pending.values())
            return max(0.0, (now - oldest) / 1000.0)

    async def lookup_published(self, outbox_event_id: UUID) -> str | None:
        async with self._lock:
            return self._dedupe.get(outbox_event_id)

    async def has_message(self, stream_message_id: str) -> bool:
        async with self._lock:
            entry = self._entries.get(stream_message_id)
            return entry is not None and not entry.acked
