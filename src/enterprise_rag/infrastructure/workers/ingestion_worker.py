"""Ingestion worker that drains Redis Streams via resumable stages."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from enterprise_rag.application.ingestion.orchestrator import OrchestrationResult
from enterprise_rag.application.ingestion.stage_pipeline import run_document_pipeline
from enterprise_rag.domain.ingestion.queue import PendingStreamEntry
from enterprise_rag.domain.ingestion.records import IngestionRunRecord, IngestionStageRecord
from enterprise_rag.domain.ingestion.retry import IngestionTaskMessage
from enterprise_rag.domain.ingestion.stages import (
    SUCCESSFUL_RUN_STATUSES,
    IngestionRunStatus,
)
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.observability.metrics import get_metrics
from enterprise_rag.shared.exceptions import IngestionError
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)

RunLoader = Callable[
    [TenantContext, UUID],
    tuple[IngestionRunRecord, list[IngestionStageRecord]]
    | Awaitable[tuple[IngestionRunRecord, list[IngestionStageRecord]]],
]
RunPersister = Callable[
    [TenantContext, IngestionRunRecord, list[IngestionStageRecord]],
    Awaitable[None] | None,
]
PipelineRunner = Callable[..., Awaitable[OrchestrationResult]]


async def _maybe_await[T](value: T | Awaitable[T]) -> T:
    if isinstance(value, Awaitable):
        return await value
    return value


def _ack_token(message: IngestionTaskMessage) -> object:
    return message.stream_message_id or message.task_id


def heartbeat_is_stale(
    heartbeat_at: datetime | None,
    *,
    stale_after: timedelta,
    now: datetime | None = None,
) -> bool:
    if heartbeat_at is None:
        return True
    current = now or datetime.now(UTC)
    ts = heartbeat_at if heartbeat_at.tzinfo else heartbeat_at.replace(tzinfo=UTC)
    return current - ts >= stale_after


@dataclass
class WorkerTickResult:
    """Outcome of processing zero or one queued task."""

    processed: bool
    result: OrchestrationResult | None = None
    task: IngestionTaskMessage | None = None
    acknowledged: bool = False
    reclaimed: bool = False


class IngestionWorker:
    """Pull tasks, run orchestration, persist progress, dead-letter failures.

    Redis delivery is at-least-once. Messages are ACKed only after a durable
    successful terminal state, or after a dead-letter write for permanent
    failure.
    """

    def __init__(
        self,
        *,
        queue: object,
        dead_letter_store: object,
        load_run: RunLoader,
        persist_run: RunPersister,
        process_service: object | None = None,
        orchestrator: object | None = None,
        worker_id: str = "worker-1",
        heartbeat_stale_seconds: float = 90.0,
        reclaim_idle_seconds: float = 120.0,
        heartbeat_seconds: float = 15.0,
        run_pipeline: PipelineRunner | None = None,
        stopping: asyncio.Event | None = None,
    ) -> None:
        self._queue = queue
        self._dead_letters = dead_letter_store
        self._load_run = load_run
        self._persist_run = persist_run
        self._process_service = process_service
        self._orchestrator = orchestrator
        self.worker_id = worker_id
        self._stale_after = timedelta(seconds=heartbeat_stale_seconds)
        self._reclaim_idle_ms = int(reclaim_idle_seconds * 1000)
        self._heartbeat_seconds = heartbeat_seconds
        self._run_pipeline = run_pipeline
        self._stopping = stopping or asyncio.Event()

    def request_stop(self) -> None:
        self._stopping.set()

    def _should_stop(self) -> bool:
        return self._stopping.is_set()

    async def process_one(self, *, timeout_seconds: float = 0.01) -> WorkerTickResult:
        if self._should_stop():
            return WorkerTickResult(processed=False)
        reclaimed = False
        message = await self._reclaim_if_stale()
        if message is not None:
            reclaimed = True
        else:
            message = await self._queue.dequeue(timeout_seconds=timeout_seconds)
        if message is None:
            return WorkerTickResult(processed=False)

        tenant = TenantContext(tenant_id=message.tenant_id)
        run, stages = await _maybe_await(self._load_run(tenant, message.ingestion_run_id))
        if run.ingestion_run_id != message.ingestion_run_id:
            raise IngestionError("Loaded run does not match task message")

        run.content_hash = run.content_hash or message.content_hash
        run.config_fingerprint = run.config_fingerprint or message.config_fingerprint
        run.correlation_id = run.correlation_id or message.correlation_id

        if run.status in SUCCESSFUL_RUN_STATUSES:
            await self._queue.acknowledge(_ack_token(message))
            return WorkerTickResult(
                processed=True, task=message, acknowledged=True, reclaimed=reclaimed
            )

        if (
            run.status is IngestionRunStatus.RUNNING
            and run.worker_id
            and run.worker_id != self.worker_id
            and not heartbeat_is_stale(run.heartbeat_at, stale_after=self._stale_after)
        ):
            # Another live worker owns the original delivery; ACK this duplicate.
            await self._queue.acknowledge(_ack_token(message))
            return WorkerTickResult(
                processed=True, task=message, acknowledged=True, reclaimed=reclaimed
            )

        run.worker_id = self.worker_id
        run.heartbeat_at = datetime.now(UTC)
        await _maybe_await(self._persist_run(tenant, run, stages))

        heartbeat_task = asyncio.create_task(self._heartbeat_loop(tenant, run, stages))
        try:
            result = await self._execute(tenant, run, stages, message)
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

        if result.dead_letter is not None:
            if result.dead_letter.original_stream_id is None:
                result.dead_letter.original_stream_id = message.stream_message_id
            if result.dead_letter.correlation_id is None:
                result.dead_letter.correlation_id = message.correlation_id
            await self._dead_letters.append(tenant, result.dead_letter)
            get_metrics().incr("ingest_dlq_total")
            logger.error(
                "ingestion_dead_lettered",
                ingestion_run_id=str(run.ingestion_run_id),
                stage=result.dead_letter.stage.value,
                attempts=result.dead_letter.attempt_count,
                original_stream_id=result.dead_letter.original_stream_id,
                correlation_id=result.dead_letter.correlation_id,
            )
            await _maybe_await(self._persist_run(tenant, run, stages))
            await self._queue.acknowledge(_ack_token(message))
            return WorkerTickResult(
                processed=True,
                result=result,
                task=message,
                acknowledged=True,
                reclaimed=reclaimed,
            )

        await _maybe_await(self._persist_run(tenant, run, stages))
        if run.status in SUCCESSFUL_RUN_STATUSES:
            await self._queue.acknowledge(_ack_token(message))
            return WorkerTickResult(
                processed=True,
                result=result,
                task=message,
                acknowledged=True,
                reclaimed=reclaimed,
            )
        logger.info(
            "ingestion_left_unacked",
            ingestion_run_id=str(run.ingestion_run_id),
            status=run.status.value,
            worker_id=self.worker_id,
        )
        return WorkerTickResult(
            processed=True,
            result=result,
            task=message,
            acknowledged=False,
            reclaimed=reclaimed,
        )

    async def _execute(
        self,
        tenant: TenantContext,
        run: IngestionRunRecord,
        stages: list[IngestionStageRecord],
        message: IngestionTaskMessage,
    ) -> OrchestrationResult:
        if self._run_pipeline is not None:
            return await self._run_pipeline(
                tenant=tenant,
                run=run,
                stages=stages,
                message=message,
                worker_id=self.worker_id,
                should_stop=self._should_stop,
            )
        if self._process_service is not None:
            return await run_document_pipeline(
                self._process_service,
                tenant,
                run.ingestion_run_id,
                worker_id=self.worker_id,
                should_stop=self._should_stop,
                stream_message_id=message.stream_message_id,
            )
        if self._orchestrator is None:
            raise IngestionError("Worker has no pipeline or orchestrator")
        return await self._orchestrator.run(tenant=tenant, run=run, stage_records=stages)

    async def _reclaim_if_stale(self) -> IngestionTaskMessage | None:
        if self._should_stop() or not hasattr(self._queue, "pending_entries"):
            return None
        try:
            pending: list[PendingStreamEntry] = await self._queue.pending_entries(
                idle_ms=self._reclaim_idle_ms
            )
        except Exception:
            logger.debug("pending_entries_failed", exc_info=True)
            return None
        for entry in pending:
            if entry.ingestion_run_id is None or entry.tenant_id is None:
                continue
            tenant = TenantContext(tenant_id=entry.tenant_id)
            try:
                run, _stages = await _maybe_await(self._load_run(tenant, entry.ingestion_run_id))
            except Exception:
                logger.debug(
                    "reclaim_load_run_failed",
                    stream_message_id=entry.stream_message_id,
                    exc_info=True,
                )
                continue
            if not heartbeat_is_stale(run.heartbeat_at, stale_after=self._stale_after):
                continue
            claimed = await self._queue.claim(
                entry.stream_message_id, min_idle_ms=self._reclaim_idle_ms
            )
            if claimed is None:
                continue
            logger.warning(
                "ingestion_reclaimed",
                stream_message_id=entry.stream_message_id,
                ingestion_run_id=str(entry.ingestion_run_id),
                idle_ms=entry.idle_ms,
                previous_consumer=entry.consumer_name,
                worker_id=self.worker_id,
            )
            return claimed
        return None

    async def _heartbeat_loop(
        self,
        tenant: TenantContext,
        run: IngestionRunRecord,
        stages: list[IngestionStageRecord],
    ) -> None:
        # NOTE: intentionally does not persist to the DB here. This loop runs
        # concurrently with the main pipeline execution, which shares the
        # same non-concurrency-safe AsyncSession; a concurrent write here
        # corrupts that session's state and breaks the pipeline's own next
        # write, regardless of which write is at fault. Giving this loop its
        # own dedicated session is the proper fix; until then this only
        # updates the in-memory record, which is a safe no-op for the
        # current single-worker-replica deployment (heartbeat staleness
        # detection only matters for reclaiming work from a genuinely dead
        # worker across multiple replicas).
        _ = tenant, stages
        while not self._should_stop():
            await asyncio.sleep(self._heartbeat_seconds)
            run.heartbeat_at = datetime.now(UTC)
            run.worker_id = self.worker_id
            get_metrics().set_gauge(
                "ingest_worker_heartbeat_timestamp", run.heartbeat_at.timestamp()
            )

    async def run_forever(self, *, poll_interval_seconds: float = 1.0) -> None:
        while not self._should_stop():
            tick = await self.process_one(timeout_seconds=poll_interval_seconds)
            if not tick.processed:
                continue
