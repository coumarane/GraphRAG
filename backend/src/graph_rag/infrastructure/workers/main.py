"""Worker process entrypoint used by Docker and CLI."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import threading
from collections.abc import Callable
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def _ready_from_container(loop: asyncio.AbstractEventLoop, container: Any) -> bool:
    """Run readiness on the ingestion loop. A blocked loop fails readiness only."""

    async def _check() -> bool:
        for check in container.ready_checks:
            result = check()
            if hasattr(result, "__await__"):
                result = await result
            if not result:
                return False
        return True

    if loop.is_closed():
        return False
    future = asyncio.run_coroutine_threadsafe(_check(), loop)
    try:
        return bool(future.result(timeout=4))
    except Exception:
        return False


def start_health_acceptor(
    *,
    host: str,
    port: int,
    ready_check: Callable[[], bool],
) -> ThreadingHTTPServer:
    """Serve /health/live on a thread that is not the ingestion event loop."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path.startswith("/health/live"):
                self._write(200, b"ok")
                return
            if path.startswith("/health/ready"):
                ready = ready_check()
                self._write(200 if ready else 503, b"ok" if ready else b"unavailable")
                return
            self._write(404, b"not found")

        def _write(self, status: int, body: bytes) -> None:
            reason = "OK" if status == 200 else "ERR"
            self.send_response(status, reason)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), _Handler)
    thread = threading.Thread(target=server.serve_forever, name="worker-health", daemon=True)
    thread.start()
    return server


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

    worker_id = _worker_id(settings.worker.consumer_name)

    async def persist_heartbeat(
        tenant: TenantContext,
        run_id: UUID,
        stamp: datetime,
    ) -> None:
        factory = container.db_session_factory
        if factory is None:
            return
        from graph_rag.infrastructure.persistence.postgres.repositories.ingestion import (
            SqlAlchemyIngestionRepository,
        )

        session = factory()
        if session is container.db_session:
            raise RuntimeError("heartbeat session must not be the pipeline session")
        try:
            repo = SqlAlchemyIngestionRepository(session)
            await repo.touch_heartbeat(tenant, run_id, stamp, worker_id)
            await session.commit()
        finally:
            await session.close()

    worker = IngestionWorker(
        queue=queue,
        dead_letter_store=dead_letters,
        load_run=load_run,
        persist_run=persist_run,
        process_service=container.require_process_ingestion(),
        worker_id=worker_id,
        heartbeat_stale_seconds=settings.worker.heartbeat_stale_seconds,
        reclaim_idle_seconds=settings.worker.reclaim_idle_seconds,
        heartbeat_seconds=settings.worker.heartbeat_seconds,
        stopping=stop,
        verify_original=verify_original,
        persist_heartbeat=persist_heartbeat,
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

    health_server = start_health_acceptor(
        host="0.0.0.0",  # noqa: S104  # readiness probes reach the pod IP
        port=8081,
        ready_check=lambda: _ready_from_container(loop, container),
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
        health_server.shutdown()
        health_server.server_close()
        publisher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await publisher_task
        logger.info("worker_stopped", worker_id=worker.worker_id)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
