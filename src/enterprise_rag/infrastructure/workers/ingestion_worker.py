"""Ingestion worker that drains the task queue via the orchestrator."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from enterprise_rag.application.ingestion.orchestrator import (
    IngestionOrchestrator,
    OrchestrationResult,
)
from enterprise_rag.domain.ingestion.queue import DeadLetterStore, IngestionTaskQueue
from enterprise_rag.domain.ingestion.records import IngestionRunRecord, IngestionStageRecord
from enterprise_rag.domain.ingestion.retry import IngestionTaskMessage
from enterprise_rag.domain.tenant import TenantContext
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


async def _maybe_await[T](value: T | Awaitable[T]) -> T:
    if isinstance(value, Awaitable):
        return await value
    return value


@dataclass
class WorkerTickResult:
    """Outcome of processing zero or one queued task."""

    processed: bool
    result: OrchestrationResult | None = None
    task: IngestionTaskMessage | None = None


class IngestionWorker:
    """Pull tasks, run orchestration, persist progress, dead-letter failures."""

    def __init__(
        self,
        *,
        queue: IngestionTaskQueue,
        dead_letter_store: DeadLetterStore,
        orchestrator: IngestionOrchestrator,
        load_run: RunLoader,
        persist_run: RunPersister,
    ) -> None:
        self._queue = queue
        self._dead_letters = dead_letter_store
        self._orchestrator = orchestrator
        self._load_run = load_run
        self._persist_run = persist_run

    async def process_one(self, *, timeout_seconds: float = 0.01) -> WorkerTickResult:
        message = await self._queue.dequeue(timeout_seconds=timeout_seconds)
        if message is None:
            return WorkerTickResult(processed=False)

        tenant = TenantContext(tenant_id=message.tenant_id)
        run, stages = await _maybe_await(self._load_run(tenant, message.ingestion_run_id))
        if run.ingestion_run_id != message.ingestion_run_id:
            raise IngestionError("Loaded run does not match task message")

        # Ensure fingerprints from the queue message are applied for resume.
        run.content_hash = run.content_hash or message.content_hash
        run.config_fingerprint = run.config_fingerprint or message.config_fingerprint
        run.correlation_id = run.correlation_id or message.correlation_id

        result = await self._orchestrator.run(
            tenant=tenant,
            run=run,
            stage_records=stages,
        )
        if result.dead_letter is not None:
            await self._dead_letters.append(tenant, result.dead_letter)
            logger.error(
                "ingestion_dead_lettered",
                ingestion_run_id=str(run.ingestion_run_id),
                stage=result.dead_letter.stage.value,
                attempts=result.dead_letter.attempt_count,
            )

        await _maybe_await(self._persist_run(tenant, run, stages))
        await self._queue.acknowledge(message.task_id)
        return WorkerTickResult(processed=True, result=result, task=message)

    async def run_forever(self, *, poll_interval_seconds: float = 1.0) -> None:
        """Continuously process tasks until cancelled."""
        while True:
            tick = await self.process_one(timeout_seconds=poll_interval_seconds)
            if not tick.processed:
                continue
