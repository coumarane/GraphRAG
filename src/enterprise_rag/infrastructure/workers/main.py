"""Worker process entrypoint used by Docker and CLI."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from uuid import UUID

from enterprise_rag.application.ingestion import IngestionOrchestrator, default_noop_handlers
from enterprise_rag.application.runtime import build_local_container
from enterprise_rag.config import get_settings
from enterprise_rag.domain.ingestion.records import IngestionRunRecord, IngestionStageRecord
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.workers import (
    IngestionWorker,
    InMemoryDeadLetterStore,
    InMemoryIngestionTaskQueue,
)
from enterprise_rag.shared.exceptions import NotFoundError
from enterprise_rag.shared.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def run_worker(*, poll_interval_seconds: float | None = None) -> None:
    """Run an ingestion worker loop until cancelled."""
    settings = get_settings()
    configure_logging(
        level=settings.app.log_level,
        json_logs=settings.app.json_logs,
        service_name=f"{settings.app.service_name}-worker",
    )
    container = build_local_container(max_upload_bytes=settings.security.max_upload_bytes)
    queue = InMemoryIngestionTaskQueue()
    dead_letters = InMemoryDeadLetterStore()
    repo = container.require_ingestion_repo()

    async def load_run(
        tenant: TenantContext,
        run_id: UUID,
    ) -> tuple[IngestionRunRecord, list[IngestionStageRecord]]:
        run = await repo.get_run(tenant, run_id)
        if run is None:
            raise NotFoundError(
                "Ingestion run not found",
                details={"ingestion_run_id": str(run_id)},
            )
        stages = await repo.list_stages(tenant, run_id)
        return run, stages

    async def persist_run(
        tenant: TenantContext,
        run: IngestionRunRecord,
        stages: list[IngestionStageRecord],
    ) -> None:
        await repo.update_run(tenant, run)
        for stage in stages:
            await repo.update_stage(tenant, stage)

    worker = IngestionWorker(
        queue=queue,
        dead_letter_store=dead_letters,
        orchestrator=IngestionOrchestrator(handlers=default_noop_handlers()),
        load_run=load_run,
        persist_run=persist_run,
    )
    interval = (
        poll_interval_seconds
        if poll_interval_seconds is not None
        else settings.worker.poll_interval_seconds
    )
    stop = asyncio.Event()

    def _stop(*_args: object) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)

    logger.info("worker_started", poll_interval_seconds=interval)
    while not stop.is_set():
        tick = await worker.process_one(timeout_seconds=interval)
        if tick.processed:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue
    logger.info("worker_stopped")


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
