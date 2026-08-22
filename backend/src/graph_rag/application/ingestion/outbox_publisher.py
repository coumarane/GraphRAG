"""Publish unpublished outbox events to the ingest stream."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from graph_rag.domain.ingestion.outbox import INGEST_QUEUED_EVENT, OutboxEventRecord
from graph_rag.domain.ingestion.retry import IngestionTaskMessage
from graph_rag.domain.ingestion.stages import SUCCESSFUL_RUN_STATUSES, IngestionRunStatus
from graph_rag.infrastructure.observability.metrics import get_metrics
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)

CommitFn = Callable[[], Awaitable[None]] | None


class OutboxPublisher:
    """Poll unpublished outbox rows and XADD with duplicate-safe publication."""

    def __init__(
        self,
        outbox: object,
        queue: object,
        *,
        on_commit: CommitFn = None,
        load_run_status: Callable[[UUID, UUID], Awaitable[IngestionRunStatus | None]] | None = None,
    ) -> None:
        self._outbox = outbox
        self._queue = queue
        self._on_commit = on_commit
        self._load_run_status = load_run_status

    async def _commit(self) -> None:
        if callable(self._on_commit):
            await self._on_commit()

    async def publish_once(self, *, limit: int = 50) -> int:
        events: list[OutboxEventRecord] = await self._outbox.list_unpublished(limit=limit)
        published = 0
        metrics = get_metrics()
        for event in events:
            try:
                stream_id = await self._publish_event(event)
                if stream_id:
                    published += 1
            except Exception as exc:
                metrics.incr("ingest_publish_failures_total")
                logger.exception(
                    "outbox_publish_failed",
                    outbox_event_id=str(event.outbox_event_id),
                    error=str(exc),
                )
                await self._outbox.record_publish_failure(event.outbox_event_id, str(exc))
                await self._commit()
        await self._sweep_orphans()
        try:
            metrics.set_gauge("ingest_queue_depth", float(await self._queue.depth()))
            if hasattr(self._queue, "pending_count"):
                metrics.set_gauge(
                    "ingest_pending_entries",
                    float(await self._queue.pending_count()),
                )
            if hasattr(self._queue, "oldest_pending_age_seconds"):
                age = await self._queue.oldest_pending_age_seconds()
                metrics.set_gauge("ingest_oldest_pending_age_seconds", float(age or 0.0))
        except Exception:
            logger.debug("outbox_metrics_failed", exc_info=True)
        return published

    async def _publish_event(self, event: OutboxEventRecord) -> str | None:
        if event.stream_message_id:
            existing = event.stream_message_id
            if hasattr(self._queue, "has_message") and await self._queue.has_message(existing):
                await self._outbox.mark_published(event.outbox_event_id, existing)
                await self._commit()
                return existing
        if hasattr(self._queue, "lookup_published"):
            deduped = await self._queue.lookup_published(event.outbox_event_id)
            if deduped:
                await self._outbox.mark_published(event.outbox_event_id, deduped)
                await self._commit()
                return deduped
        message = IngestionTaskMessage.model_validate(
            {
                **event.payload,
                "outbox_event_id": str(event.outbox_event_id),
                "tenant_id": str(event.tenant_id),
                "ingestion_run_id": str(event.aggregate_id),
            }
        )
        stream_id = await self._queue.enqueue(message)
        if not stream_id:
            raise RuntimeError("queue enqueue returned no stream id")
        await self._outbox.mark_published(event.outbox_event_id, str(stream_id))
        await self._commit()
        return str(stream_id)

    async def _sweep_orphans(self) -> None:
        """Republish jobs whose stream entries vanished (Redis restart)."""
        if self._load_run_status is None or not hasattr(self._queue, "has_message"):
            return
        published = await self._outbox.list_published_for_sweeper(limit=50)
        for event in published:
            if event.event_type != INGEST_QUEUED_EVENT or not event.stream_message_id:
                continue
            if await self._queue.has_message(event.stream_message_id):
                continue
            status = await self._load_run_status(event.tenant_id, event.aggregate_id)
            if status is None or status in SUCCESSFUL_RUN_STATUSES:
                continue
            if status is IngestionRunStatus.FAILED or status is IngestionRunStatus.CANCELLED:
                continue
            logger.warning(
                "outbox_orphan_republish",
                outbox_event_id=str(event.outbox_event_id),
                ingestion_run_id=str(event.aggregate_id),
                missing_stream_id=event.stream_message_id,
            )
            message = IngestionTaskMessage.model_validate(
                {
                    **event.payload,
                    "outbox_event_id": str(event.outbox_event_id),
                    "tenant_id": str(event.tenant_id),
                    "ingestion_run_id": str(event.aggregate_id),
                }
            )
            # Duplicate publication is expected after Redis restart.
            stream_id = await self._queue.enqueue(message)
            await self._outbox.mark_published(event.outbox_event_id, str(stream_id))
            await self._commit()
