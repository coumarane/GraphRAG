"""Reliability tests for outbox → Redis Streams → worker reclaim/DLQ/resume."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from enterprise_rag.application.ingestion.enqueue import enqueue_ingest_run
from enterprise_rag.application.ingestion.handlers import (
    CallableStageHandler,
    default_noop_handlers,
)
from enterprise_rag.application.ingestion.orchestrator import (
    IngestionOrchestrator,
    OrchestrationResult,
)
from enterprise_rag.application.ingestion.outbox_publisher import OutboxPublisher
from enterprise_rag.domain.ids import content_sha256_hex, new_id
from enterprise_rag.domain.ingestion import (
    INGESTION_STAGE_ORDER,
    DeadLetterRecord,
    IngestionRunRecord,
    IngestionRunStatus,
    IngestionStageName,
    IngestionTaskMessage,
    RetryPolicy,
    StageContext,
    StageOutcome,
    StageOutcomeStatus,
    StageStatus,
    build_persisted_stage_records,
)
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.persistence.dead_letters import InMemoryDeadLetterStore
from enterprise_rag.infrastructure.persistence.outbox import InMemoryOutboxStore
from enterprise_rag.infrastructure.persistence.redis import InMemoryStreamIngestionQueue
from enterprise_rag.infrastructure.workers import IngestionWorker
from enterprise_rag.shared.exceptions import PermanentError, TransientError


def _bundle() -> tuple[TenantContext, IngestionRunRecord, list]:
    tenant_id = new_id()
    run_id = new_id()
    tenant = TenantContext(tenant_id=tenant_id)
    run = IngestionRunRecord(
        ingestion_run_id=run_id,
        tenant_id=tenant_id,
        document_id=new_id(),
        version_id=new_id(),
        content_hash=content_sha256_hex("doc-bytes"),
        config_fingerprint="fp-v1",
        correlation_id="corr-rel",
    )
    stages = build_persisted_stage_records(tenant_id=tenant_id, ingestion_run_id=run_id)
    return tenant, run, stages


def _store(run: IngestionRunRecord, stages: list) -> dict:
    return {"run": run, "stages": stages}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_crash_after_postgres_commit_publisher_recovers() -> None:
    tenant, run, stages = _bundle()
    outbox = InMemoryOutboxStore()
    queue = InMemoryStreamIngestionQueue()
    await enqueue_ingest_run(outbox, tenant=tenant, run=run)
    unpublished = await outbox.list_unpublished()
    assert unpublished and unpublished[0].published_at is None

    publisher = OutboxPublisher(outbox, queue)
    published = await publisher.publish_once()
    assert published == 1
    event = await outbox.get(unpublished[0].outbox_event_id)
    assert event is not None
    assert event.stream_message_id
    assert event.published_at is not None
    message = await queue.dequeue(timeout_seconds=0.01)
    assert message is not None
    assert message.ingestion_run_id == run.ingestion_run_id
    _ = stages


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_outbox_publication_reuses_stream_id() -> None:
    tenant, run, _stages = _bundle()
    outbox = InMemoryOutboxStore()
    queue = InMemoryStreamIngestionQueue()
    event = await enqueue_ingest_run(outbox, tenant=tenant, run=run)
    publisher = OutboxPublisher(outbox, queue)
    await publisher.publish_once()
    first = (await outbox.get(event.outbox_event_id)).stream_message_id
    # Simulate crash after XADD before published_at was visible, then retry.
    stored = await outbox.get(event.outbox_event_id)
    stored.published_at = None
    await publisher.publish_once()
    second = (await outbox.get(event.outbox_event_id)).stream_message_id
    assert first == second
    assert await queue.depth() == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_crash_mid_stage_leaves_message_unacked() -> None:
    tenant, run, stages = _bundle()
    store = _store(run, stages)
    queue = InMemoryStreamIngestionQueue()
    dead = InMemoryDeadLetterStore()
    started = {"count": 0}

    async def pipeline(**kwargs):
        started["count"] += 1
        kwargs["run"].status = IngestionRunStatus.RUNNING
        kwargs["stages"][0].status = StageStatus.RUNNING
        kwargs["stages"][0].attempt_count = 1
        from enterprise_rag.domain.ingestion.state_machine import IngestionProgress

        return OrchestrationResult(
            run_status=IngestionRunStatus.RUNNING,
            progress=IngestionProgress(
                current_stage=IngestionStageName.VALIDATE,
                completed_stages=[],
                pages_processed=0,
                elements_processed=0,
                estimated_completion_percent=1.0,
                retry_count=0,
            ),
        )

    worker = IngestionWorker(
        queue=queue,
        dead_letter_store=dead,
        load_run=lambda _t, _id: (store["run"], store["stages"]),
        persist_run=lambda _t, updated, rows: store.update(run=updated, stages=rows),
        run_pipeline=pipeline,
        worker_id="w1",
        heartbeat_stale_seconds=90,
        reclaim_idle_seconds=1,
    )
    stream_id = await queue.enqueue(
        IngestionTaskMessage(
            tenant_id=tenant.tenant_id,
            ingestion_run_id=run.ingestion_run_id,
            document_id=run.document_id,
            version_id=run.version_id,
            content_hash=run.content_hash or "",
            config_fingerprint=run.config_fingerprint or "",
            correlation_id=run.correlation_id,
        )
    )
    tick = await worker.process_one(timeout_seconds=0.1)
    assert tick.processed
    assert not tick.acknowledged
    assert await queue.has_message(stream_id)
    assert await queue.pending_count() == 1
    assert started["count"] >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_xautoclaim_requires_idle_and_stale_heartbeat() -> None:
    tenant, run, stages = _bundle()
    run.status = IngestionRunStatus.RUNNING
    run.worker_id = "dead-worker"
    run.heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
    store = _store(run, stages)
    queue = InMemoryStreamIngestionQueue(consumer_name="w1")
    dead = InMemoryDeadLetterStore()
    stream_id = await queue.enqueue(
        IngestionTaskMessage(
            tenant_id=tenant.tenant_id,
            ingestion_run_id=run.ingestion_run_id,
            document_id=run.document_id,
            version_id=run.version_id,
            content_hash=run.content_hash or "",
            config_fingerprint=run.config_fingerprint or "",
            correlation_id=run.correlation_id,
        )
    )
    first = await queue.dequeue(timeout_seconds=0.01)
    assert first is not None
    queue.advance_clock_ms(200_000)

    async def pipeline(**kwargs):
        kwargs["run"].status = IngestionRunStatus.COMPLETED
        kwargs["run"].completed_at = datetime.now(UTC)
        for row in kwargs["stages"]:
            row.status = StageStatus.COMPLETED
        return type("R", (), {"dead_letter": None, "run_status": IngestionRunStatus.COMPLETED})()

    worker = IngestionWorker(
        queue=queue,
        dead_letter_store=dead,
        load_run=lambda _t, _id: (store["run"], store["stages"]),
        persist_run=lambda _t, updated, rows: store.update(run=updated, stages=rows),
        run_pipeline=pipeline,
        worker_id="w2",
        heartbeat_stale_seconds=90,
        reclaim_idle_seconds=120,
        heartbeat_seconds=60,
    )
    tick = await worker.process_one(timeout_seconds=0.01)
    assert tick.reclaimed
    assert tick.acknowledged
    assert not await queue.has_message(stream_id)

    # Fresh heartbeat must block reclaim even if PEL is idle.
    run2_tenant, run2, stages2 = _bundle()
    run2.status = IngestionRunStatus.RUNNING
    run2.worker_id = "live-worker"
    run2.heartbeat_at = datetime.now(UTC)
    store2 = _store(run2, stages2)
    queue2 = InMemoryStreamIngestionQueue(consumer_name="w1")
    await queue2.enqueue(
        IngestionTaskMessage(
            tenant_id=run2_tenant.tenant_id,
            ingestion_run_id=run2.ingestion_run_id,
            document_id=run2.document_id,
            version_id=run2.version_id,
            content_hash=run2.content_hash or "",
            config_fingerprint=run2.config_fingerprint or "",
        )
    )
    await queue2.dequeue(timeout_seconds=0.01)
    queue2.advance_clock_ms(200_000)
    blocked = IngestionWorker(
        queue=queue2,
        dead_letter_store=InMemoryDeadLetterStore(),
        load_run=lambda _t, _id: (store2["run"], store2["stages"]),
        persist_run=lambda *_a, **_k: None,
        run_pipeline=pipeline,
        worker_id="w2",
        heartbeat_stale_seconds=90,
        reclaim_idle_seconds=120,
    )
    tick2 = await blocked.process_one(timeout_seconds=0.01)
    assert not tick2.reclaimed
    assert await queue2.pending_count() == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_job_delivery_acks_when_already_complete() -> None:
    tenant, run, stages = _bundle()
    run.status = IngestionRunStatus.COMPLETED
    store = _store(run, stages)
    queue = InMemoryStreamIngestionQueue()
    stream_id = await queue.enqueue(
        IngestionTaskMessage(
            tenant_id=tenant.tenant_id,
            ingestion_run_id=run.ingestion_run_id,
            document_id=run.document_id,
            version_id=run.version_id,
            content_hash=run.content_hash or "",
            config_fingerprint=run.config_fingerprint or "",
        )
    )
    worker = IngestionWorker(
        queue=queue,
        dead_letter_store=InMemoryDeadLetterStore(),
        load_run=lambda _t, _id: (store["run"], store["stages"]),
        persist_run=lambda *_a, **_k: None,
        run_pipeline=lambda **_k: None,
        worker_id="w1",
    )
    tick = await worker.process_one(timeout_seconds=0.1)
    assert tick.acknowledged
    assert not await queue.has_message(stream_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_from_first_incomplete_stage() -> None:
    tenant, run, stages = _bundle()
    for row in stages:
        if row.stage in {IngestionStageName.VALIDATE, IngestionStageName.HASH}:
            row.status = StageStatus.COMPLETED
            row.idempotency_key = IngestionOrchestrator  # placeholder replaced below
    from enterprise_rag.domain.ingestion.state_machine import IngestionStateMachine

    for row in stages:
        if row.status is StageStatus.COMPLETED:
            row.idempotency_key = IngestionStateMachine.build_idempotency_key(
                tenant_id=tenant.tenant_id,
                version_id=run.version_id,
                stage=row.stage,
                config_fingerprint=run.config_fingerprint or "",
                content_hash=run.content_hash or "",
            )
            row.config_fingerprint = run.config_fingerprint
    seen: list[IngestionStageName] = []

    async def track(stage: IngestionStageName, context: StageContext) -> StageOutcome:
        _ = context
        seen.append(stage)
        return StageOutcome(status=StageOutcomeStatus.COMPLETED)

    handlers = {
        stage: CallableStageHandler(stage, lambda ctx, s=stage: track(s, ctx))
        for stage in INGESTION_STAGE_ORDER
        if stage is not IngestionStageName.SUMMARIZE_COMMUNITIES
    }
    orchestrator = IngestionOrchestrator(handlers, retry_policy=RetryPolicy(max_attempts=1))
    result = await orchestrator.run(tenant=tenant, run=run, stage_records=stages)
    assert IngestionStageName.VALIDATE not in seen
    assert IngestionStageName.HASH not in seen
    assert IngestionStageName.REGISTER_DOCUMENT in seen
    assert result.run_status in {
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.COMPLETED_WITH_WARNINGS,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_restart_republishes_orphan() -> None:
    tenant, run, _stages = _bundle()
    outbox = InMemoryOutboxStore()
    queue = InMemoryStreamIngestionQueue()
    event = await enqueue_ingest_run(outbox, tenant=tenant, run=run)

    async def load_run_status(_tenant_id, _run_id):
        return IngestionRunStatus.PENDING

    publisher = OutboxPublisher(
        outbox,
        queue,
        load_run_status=load_run_status,
    )
    await publisher.publish_once()
    queue.simulate_restart()
    assert not await queue.has_message((await outbox.get(event.outbox_event_id)).stream_message_id)
    await publisher.publish_once()
    message = await queue.dequeue(timeout_seconds=0.01)
    assert message is not None
    assert message.ingestion_run_id == run.ingestion_run_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retryable_then_permanent_and_dlq() -> None:
    tenant, run, stages = _bundle()
    _store(run, stages)
    queue = InMemoryStreamIngestionQueue()
    dead = InMemoryDeadLetterStore()
    attempts = {"n": 0}

    async def flaky(context: StageContext) -> StageOutcome:
        _ = context
        attempts["n"] += 1
        raise TransientError("blip")

    async def boom(context: StageContext) -> StageOutcome:
        _ = context
        raise PermanentError("bad input", code="bad_input")

    handlers = default_noop_handlers(skip_communities=True)
    handlers[IngestionStageName.VALIDATE] = CallableStageHandler(IngestionStageName.VALIDATE, flaky)
    retry_orch = IngestionOrchestrator(
        handlers,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.0, jitter=False),
        sleep_fn=lambda _d: None,
    )
    result = await retry_orch.run(tenant=tenant, run=run, stage_records=stages)
    assert result.dead_letter is not None
    assert attempts["n"] == 3

    tenant2, run2, stages2 = _bundle()
    handlers2 = default_noop_handlers(skip_communities=True)
    handlers2[IngestionStageName.VALIDATE] = CallableStageHandler(IngestionStageName.VALIDATE, boom)
    orch2 = IngestionOrchestrator(
        handlers2,
        retry_policy=RetryPolicy(max_attempts=5, jitter=False),
        sleep_fn=lambda _d: None,
    )

    async def pipeline(**kwargs):
        return await orch2.run(
            tenant=kwargs["tenant"],
            run=kwargs["run"],
            stage_records=kwargs["stages"],
            artifacts={"stream_message_id": kwargs["message"].stream_message_id},
        )

    store2 = _store(run2, stages2)
    await queue.enqueue(
        IngestionTaskMessage(
            tenant_id=tenant2.tenant_id,
            ingestion_run_id=run2.ingestion_run_id,
            document_id=run2.document_id,
            version_id=run2.version_id,
            content_hash=run2.content_hash or "",
            config_fingerprint=run2.config_fingerprint or "",
            correlation_id="corr-dlq",
        )
    )
    worker = IngestionWorker(
        queue=queue,
        dead_letter_store=dead,
        load_run=lambda _t, _id: (store2["run"], store2["stages"]),
        persist_run=lambda _t, updated, rows: store2.update(run=updated, stages=rows),
        run_pipeline=pipeline,
        worker_id="w1",
    )
    tick = await worker.process_one(timeout_seconds=0.1)
    assert tick.acknowledged
    assert tick.result is not None
    assert tick.result.dead_letter is not None
    listed = await dead.list_for_run(tenant2, run2.ingestion_run_id)
    assert len(listed) == 1
    record = listed[0]
    assert isinstance(record, DeadLetterRecord)
    assert record.ingestion_run_id == run2.ingestion_run_id
    assert record.tenant_id == tenant2.tenant_id
    assert record.stage is IngestionStageName.VALIDATE
    assert record.original_stream_id
    assert record.correlation_id in {"corr-dlq", "corr-rel", run2.correlation_id}
    assert record.attempt_count >= 1
    assert record.error_code == "bad_input"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graceful_shutdown_does_not_ack() -> None:
    tenant, run, stages = _bundle()
    store = _store(run, stages)
    queue = InMemoryStreamIngestionQueue()
    stop = asyncio.Event()

    async def slow(context: StageContext) -> StageOutcome:
        _ = context
        stop.set()
        await asyncio.sleep(0.05)
        return StageOutcome(status=StageOutcomeStatus.COMPLETED)

    handlers = default_noop_handlers(skip_communities=True)
    handlers[IngestionStageName.VALIDATE] = CallableStageHandler(IngestionStageName.VALIDATE, slow)
    orchestrator = IngestionOrchestrator(
        handlers,
        retry_policy=RetryPolicy(max_attempts=1),
        should_stop=stop.is_set,
        sleep_fn=lambda _d: None,
    )

    async def pipeline(**kwargs):
        return await orchestrator.run(
            tenant=kwargs["tenant"],
            run=kwargs["run"],
            stage_records=kwargs["stages"],
        )

    stream_id = await queue.enqueue(
        IngestionTaskMessage(
            tenant_id=tenant.tenant_id,
            ingestion_run_id=run.ingestion_run_id,
            document_id=run.document_id,
            version_id=run.version_id,
            content_hash=run.content_hash or "",
            config_fingerprint=run.config_fingerprint or "",
        )
    )
    worker = IngestionWorker(
        queue=queue,
        dead_letter_store=InMemoryDeadLetterStore(),
        load_run=lambda _t, _id: (store["run"], store["stages"]),
        persist_run=lambda _t, updated, rows: store.update(run=updated, stages=rows),
        run_pipeline=pipeline,
        worker_id="w1",
        stopping=stop,
    )
    tick = await worker.process_one(timeout_seconds=0.2)
    assert tick.processed
    assert not tick.acknowledged
    assert await queue.has_message(stream_id)
    assert store["run"].status is IngestionRunStatus.RUNNING
