"""A long stage keeps a persisted heartbeat on a session that is not the pipeline session."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from graph_rag.application.ingestion.progress import derive_progress_state
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.workers.ingestion_worker import (
    IngestionWorker,
    heartbeat_is_stale,
)


def _run() -> tuple[TenantContext, IngestionRunRecord]:
    tenant = TenantContext(tenant_id=new_id())
    run = IngestionRunRecord(
        ingestion_run_id=new_id(),
        tenant_id=tenant.tenant_id,
        document_id=new_id(),
        version_id=new_id(),
        content_hash=content_sha256_hex("heartbeat"),
        config_fingerprint="fp",
    )
    return tenant, run


def test_heartbeat_interval_is_at_most_sixty_seconds() -> None:
    tenant, _run_record = _run()
    worker = IngestionWorker(
        queue=object(),  # type: ignore[arg-type]
        dead_letter_store=object(),  # type: ignore[arg-type]
        load_run=lambda _tenant, _run_id: (_ for _ in ()).throw(AssertionError()),
        persist_run=lambda *_args, **_kwargs: None,
        worker_id="worker-a",
        heartbeat_seconds=120,
    )
    assert worker._heartbeat_seconds <= 60
    assert tenant.tenant_id


def test_fresh_persisted_heartbeat_is_not_stalled_or_reclaimed() -> None:
    started = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
    now = started + timedelta(seconds=180)
    heartbeat = now - timedelta(seconds=50)
    assert derive_progress_state("running", heartbeat, now=now) == "running"
    assert heartbeat_is_stale(heartbeat, stale_after=timedelta(seconds=90), now=now) is False
    stale = started
    assert derive_progress_state("running", stale, now=now) == "stalled"
    assert heartbeat_is_stale(stale, stale_after=timedelta(seconds=90), now=now) is True


@pytest.mark.asyncio
async def test_heartbeat_loop_uses_an_independent_session() -> None:
    tenant, run = _run()
    pipeline_session = object()
    seen: list[object] = []

    async def persist_run(*_args, **_kwargs) -> None:
        seen.append(pipeline_session)

    async def persist_heartbeat(_tenant, run_id, stamp) -> None:
        session = object()
        assert session is not pipeline_session
        assert run_id == run.ingestion_run_id
        seen.append(session)
        run.heartbeat_at = stamp

    worker = IngestionWorker(
        queue=object(),  # type: ignore[arg-type]
        dead_letter_store=object(),  # type: ignore[arg-type]
        load_run=lambda *_args: (_ for _ in ()).throw(AssertionError()),
        persist_run=persist_run,
        persist_heartbeat=persist_heartbeat,
        heartbeat_seconds=0.05,
        worker_id="worker-a",
    )
    task = asyncio.create_task(worker._heartbeat_loop(tenant, run))
    await asyncio.sleep(0.18)
    worker.request_stop()
    await task
    heartbeat_sessions = [item for item in seen if item is not pipeline_session]
    assert heartbeat_sessions
    assert pipeline_session not in heartbeat_sessions
    assert run.heartbeat_at is not None
    assert derive_progress_state("running", run.heartbeat_at) == "running"
