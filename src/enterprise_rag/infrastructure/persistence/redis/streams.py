"""Redis Streams ingestion queue (at-least-once consumer group)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from enterprise_rag.domain.ingestion.queue import PendingStreamEntry
from enterprise_rag.domain.ingestion.retry import IngestionTaskMessage
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)

_DEDUPE_PREFIX = "ingest:outbox:"


def _message_from_fields(message_id: str, fields: dict[str, Any]) -> IngestionTaskMessage:
    payload = fields.get("payload") or fields.get(b"payload")
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = {
            str(key): (value.decode("utf-8") if isinstance(value, bytes) else value)
            for key, value in fields.items()
        }
        if "payload" in data:
            data = json.loads(str(data["payload"]))
    data["stream_message_id"] = message_id
    return IngestionTaskMessage.model_validate(data)


def _to_fields(message: IngestionTaskMessage) -> dict[str, str]:
    payload = message.model_dump(mode="json")
    return {"payload": json.dumps(payload)}


class RedisStreamIngestionQueue:
    """XADD / XREADGROUP / XACK / XPENDING / XCLAIM adapter."""

    def __init__(
        self,
        redis: Any,
        *,
        stream_key: str = "ingestion-jobs",
        group_name: str = "ingestion-workers",
        consumer_name: str = "worker-1",
    ) -> None:
        self._redis = redis
        self.stream_key = stream_key
        self.group_name = group_name
        self.consumer_name = consumer_name
        self._group_ready = False

    async def ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self._redis.xgroup_create(
                self.stream_key,
                self.group_name,
                id="0-0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._group_ready = True

    async def enqueue(self, message: IngestionTaskMessage) -> str:
        await self.ensure_group()
        if message.outbox_event_id is not None:
            existing = await self.lookup_published(message.outbox_event_id)
            if existing is not None and await self.has_message(existing):
                message.stream_message_id = existing
                return existing
        message_id = await self._redis.xadd(self.stream_key, _to_fields(message))
        stream_id = message_id.decode("utf-8") if isinstance(message_id, bytes) else str(message_id)
        if message.outbox_event_id is not None:
            await self._redis.set(f"{_DEDUPE_PREFIX}{message.outbox_event_id}", stream_id)
        message.stream_message_id = stream_id
        return stream_id

    async def dequeue(self, *, timeout_seconds: float | None = None) -> IngestionTaskMessage | None:
        await self.ensure_group()
        block_ms = 0 if timeout_seconds is None else max(1, int(timeout_seconds * 1000))
        rows = await self._redis.xreadgroup(
            groupname=self.group_name,
            consumername=self.consumer_name,
            streams={self.stream_key: ">"},
            count=1,
            block=block_ms,
        )
        if not rows:
            return None
        _stream, messages = rows[0]
        if not messages:
            return None
        message_id, fields = messages[0]
        stream_id = message_id.decode("utf-8") if isinstance(message_id, bytes) else str(message_id)
        return _message_from_fields(stream_id, fields)

    async def acknowledge(self, task_id: object) -> None:
        await self.ensure_group()
        await self._redis.xack(self.stream_key, self.group_name, str(task_id))

    async def depth(self) -> int:
        await self.ensure_group()
        length = int(await self._redis.xlen(self.stream_key))
        pending = await self.pending_count()
        return max(length, pending)

    async def pending_entries(self, *, idle_ms: int = 0) -> list[PendingStreamEntry]:
        await self.ensure_group()
        rows = await self._redis.xpending_range(
            self.stream_key,
            self.group_name,
            min="-",
            max="+",
            count=100,
        )
        entries: list[PendingStreamEntry] = []
        for row in rows or []:
            message_id = row.get("message_id") or row.get(b"message_id")
            consumer = row.get("consumer") or row.get(b"consumer") or ""
            idle = int(row.get("time_since_delivered") or row.get("idle") or 0)
            delivery = int(row.get("times_delivered") or row.get("delivery_count") or 1)
            if isinstance(message_id, bytes):
                message_id = message_id.decode("utf-8")
            if isinstance(consumer, bytes):
                consumer = consumer.decode("utf-8")
            if idle < idle_ms:
                continue
            entries.append(
                PendingStreamEntry(
                    stream_message_id=str(message_id),
                    consumer_name=str(consumer),
                    idle_ms=idle,
                    delivery_count=delivery,
                )
            )
        return entries

    async def claim(
        self,
        stream_message_id: str,
        *,
        min_idle_ms: int,
    ) -> IngestionTaskMessage | None:
        await self.ensure_group()
        claimed = await self._redis.xclaim(
            self.stream_key,
            self.group_name,
            self.consumer_name,
            min_idle_ms,
            [stream_message_id],
        )
        if not claimed:
            return None
        message_id, fields = claimed[0]
        stream_id = message_id.decode("utf-8") if isinstance(message_id, bytes) else str(message_id)
        return _message_from_fields(stream_id, fields)

    async def pending_count(self) -> int:
        await self.ensure_group()
        info = await self._redis.xpending(self.stream_key, self.group_name)
        if not info:
            return 0
        if isinstance(info, dict):
            return int(info.get("pending") or info.get("count") or 0)
        return int(info[0]) if info else 0

    async def oldest_pending_age_seconds(self) -> float | None:
        entries = await self.pending_entries(idle_ms=0)
        if not entries:
            return None
        return max(item.idle_ms for item in entries) / 1000.0

    async def lookup_published(self, outbox_event_id: UUID) -> str | None:
        value = await self._redis.get(f"{_DEDUPE_PREFIX}{outbox_event_id}")
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    async def has_message(self, stream_message_id: str) -> bool:
        try:
            rows = await self._redis.xrange(
                self.stream_key, min=stream_message_id, max=stream_message_id, count=1
            )
        except Exception:
            return False
        return bool(rows)
