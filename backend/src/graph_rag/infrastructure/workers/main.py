"""Worker process entrypoint used by Docker and CLI."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
from typing import Any
from uuid import UUID

from graph_rag.application.runtime import build_runtime_container
from graph_rag.config import get_settings
from graph_rag.domain.ingestion.records import IngestionRunRecord, IngestionStageRecord
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.workers import IngestionWorker
from graph_rag.shared.exceptions import NotFoundError
from graph_rag.shared.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def _health_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    container: Any,
) -> None:
    try:
        raw = await reader.read(1024)
        line = raw.decode("latin1", errors="ignore").split("\r\n", 1)[0]
        path = line.split(" ")[1] if " " in line else "/"
        if path.startswith("/health/live"):
            status, body = 200, b"ok"
        elif path.startswith("/health/ready"):
            ready = True
            for check in container.ready_checks:
                result = check()
                if hasattr(result, "__await__"):
                    result = await result
                if not result:
                    ready = False
                    break
            status, body = (200, b"ok") if ready else (503, b"unavailable")
        else:
            status, body = 404, b"not found"
        writer.write(
            f"HTTP/1.1 {status} {'OK' if status == 200 else 'ERR'}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def _worker_id(settings_name: str) -> str:
    host = socket.gethostname()
    return settings_name or f"{host}-{os.getpid()}"


async def run_worker(*, poll_interval_seconds: float | None = None) -> None:
    """Run an ingestion worker loop until cancelled."""
    settings = get_settings()
    configure_logging(
        level=settings.app.log_level,
        json_logs=settings.app.json_logs,
        service_name=f"{settings.app.service_name}-worker",
    )
    container = build_runtime_container(settings)
    if container.ingest_queue is not None and hasattr(container.ingest_queue, "consumer_name"):
        container.ingest_queue.consumer_name = _worker_id(settings.worker.consumer_name)
    repo = container.require_ingestion_repo()
    queue = container.ingest_queue
    if queue is None:
        raise RuntimeError("Ingest queue is not configured")
    dead_letters = container.dead_letter_store
    if dead_letters is None:
        raise RuntimeError("Dead-letter store is not configured")

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
        await container.commit_db()

    stop = asyncio.Event()
    async def verify_original(tenant: TenantContext, run: IngestionRunRecord) -> str | None:
        version = await container.require_document_repo().get_version(tenant, run.version_id)
        if version is None or not version.original_object_key or not version.etag:
            return None
        store = container.object_store
        if store is None:
            return "object_store_unavailable"
        head = await store.head_object(tenant, object_key=version.original_object_key)
        if head.byte_size != (version.byte_size or 0) or head.etag != version.etag:
            return "object_changed"
        return None

    worker = IngestionWorker(
        queue=queue,
        dead_letter_store=dead_letters,
        load_run=load_run,
        persist_run=persist_run,
        process_service=container.require_process_ingestion(),
        worker_id=_worker_id(settings.worker.consumer_name),
        heartbeat_stale_seconds=settings.worker.heartbeat_stale_seconds,
        reclaim_idle_seconds=settings.worker.reclaim_idle_seconds,
        heartbeat_seconds=settings.worker.heartbeat_seconds,
        stopping=stop,
        verify_original=verify_original,
    )
    interval = (
        poll_interval_seconds
        if poll_interval_seconds is not None
        else settings.worker.poll_interval_seconds
    )

    def _stop(*_args: object) -> None:
        worker.request_stop()
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)

    # The outbox publisher loop and the main pipeline both write through the
    # single shared AsyncSession on `container`, which is not safe for
    # concurrent use by multiple coroutines. Serialize access with a lock
    # rather than let them race, which corrupts the session's state and
    # crashes whichever side writes next.
    db_lock = asyncio.Lock()

    async def _publish_loop() -> None:
        publisher = container.outbox_publisher
        if publisher is None:
            return
        while not stop.is_set():
            try:
                async with db_lock:
                    await publisher.publish_once()
            except Exception:
                logger.exception("worker_outbox_publish_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker.outbox_poll_seconds)
            except TimeoutError:
                continue

    health_server = await asyncio.start_server(
        lambda reader, writer: _health_connection(reader, writer, container),
        host="0.0.0.0",  # noqa: S104  # readiness probes reach the pod IP
        port=8081,
    )
    logger.info(
        "worker_started",
        poll_interval_seconds=interval,
        worker_id=worker.worker_id,
        stream_key=settings.worker.stream_key,
    )
    publisher_task = asyncio.create_task(_publish_loop())
    try:
        while not stop.is_set():
            async with db_lock:
                tick = await worker.process_one(timeout_seconds=interval)
            if tick.processed:
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                continue
    finally:
        health_server.close()
        await health_server.wait_closed()
        publisher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await publisher_task
        logger.info("worker_stopped", worker_id=worker.worker_id)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
