"""Ingestion orchestration, retry and worker tests."""

from __future__ import annotations

from uuid import UUID

import pytest

from graph_rag.application.ingestion import (
    CallableStageHandler,
    IngestionOrchestrator,
    default_noop_handlers,
)
from graph_rag.application.ingestion.orchestrator import MAX_TOTAL_STAGE_ATTEMPTS
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.ingestion import (
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
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.workers import (
    IngestionWorker,
    InMemoryDeadLetterStore,
    InMemoryIngestionTaskQueue,
)
from graph_rag.shared.exceptions import PermanentError, TransientError


def _run_bundle() -> tuple[TenantContext, IngestionRunRecord, list]:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    run_id = new_id()
    tenant = TenantContext(tenant_id=tenant_id)
    run = IngestionRunRecord(
        ingestion_run_id=run_id,
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        content_hash=content_sha256_hex("doc-bytes"),
        config_fingerprint="fp-v1",
        correlation_id="corr-1",
    )
    stages = build_persisted_stage_records(tenant_id=tenant_id, ingestion_run_id=run_id)
    return tenant, run, stages


@pytest.mark.asyncio
async def test_orchestrator_runs_full_pipeline_with_optional_skip() -> None:
    tenant, run, stages = _run_bundle()
    handlers = default_noop_handlers(skip_communities=True)
    orchestrator = IngestionOrchestrator(handlers, retry_policy=RetryPolicy(max_attempts=1))
    result = await orchestrator.run(tenant=tenant, run=run, stage_records=stages)
    assert result.run_status in {
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.COMPLETED_WITH_WARNINGS,
    }
    assert result.progress.estimated_completion_percent == 100.0
    assert IngestionStageName.SUMMARIZE_COMMUNITIES in result.skipped_in_session
    assert stages[-1].status is StageStatus.COMPLETED
    community = next(s for s in stages if s.stage is IngestionStageName.SUMMARIZE_COMMUNITIES)
    assert community.status is StageStatus.SKIPPED


@pytest.mark.asyncio
async def test_orchestrator_resumes_completed_stages() -> None:
    tenant, run, stages = _run_bundle()
    handlers = default_noop_handlers(skip_communities=True)
    orchestrator = IngestionOrchestrator(handlers, sleep_fn=lambda _d: None)
    first = await orchestrator.run(
        tenant=tenant,
        run=run,
        stage_records=stages,
        stop_after=IngestionStageName.HASH,
    )
    assert IngestionStageName.VALIDATE in first.completed_in_session
    assert IngestionStageName.HASH in first.completed_in_session

    second = await orchestrator.run(tenant=tenant, run=run, stage_records=stages)
    assert IngestionStageName.VALIDATE in second.skipped_in_session
    assert IngestionStageName.HASH in second.skipped_in_session
    assert second.run_status in {
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.COMPLETED_WITH_WARNINGS,
    }


@pytest.mark.asyncio
async def test_retry_then_success() -> None:
    tenant, run, stages = _run_bundle()
    attempts = {"count": 0}

    async def flaky(context: StageContext) -> StageOutcome:
        _ = context
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TransientError("temporary glitch")
        return StageOutcome(status=StageOutcomeStatus.COMPLETED)

    handlers = default_noop_handlers(skip_communities=True)
    handlers[IngestionStageName.VALIDATE] = CallableStageHandler(
        IngestionStageName.VALIDATE, flaky
    )
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    orchestrator = IngestionOrchestrator(
        handlers,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.01, jitter=False),
        sleep_fn=fake_sleep,
    )
    result = await orchestrator.run(tenant=tenant, run=run, stage_records=stages)
    assert result.run_status in {
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.COMPLETED_WITH_WARNINGS,
    }
    assert attempts["count"] == 3
    assert len(sleeps) == 2
    assert result.progress.retry_count >= 2


@pytest.mark.asyncio
async def test_permanent_failure_dead_letters() -> None:
    tenant, run, stages = _run_bundle()

    async def boom(context: StageContext) -> StageOutcome:
        _ = context
        raise PermanentError("bad input", code="bad_input")

    handlers = default_noop_handlers(skip_communities=True)
    handlers[IngestionStageName.VALIDATE] = CallableStageHandler(
        IngestionStageName.VALIDATE, boom
    )
    orchestrator = IngestionOrchestrator(
        handlers,
        retry_policy=RetryPolicy(max_attempts=5, jitter=False),
        sleep_fn=lambda _d: None,
    )
    result = await orchestrator.run(tenant=tenant, run=run, stage_records=stages)
    assert result.run_status is IngestionRunStatus.FAILED
    assert result.failed_stage is IngestionStageName.VALIDATE
    assert result.dead_letter is not None
    assert result.dead_letter.attempt_count == 1
    assert result.dead_letter.error_code == "bad_input"


@pytest.mark.asyncio
async def test_max_total_stage_attempts_caps_runaway_redispatch() -> None:
    """A stage must never retry forever across separate orchestrator.run()
    invocations (e.g. a duplicate outbox/stream redispatch), even though
    RetryPolicy.max_attempts only bounds retries within a single invocation.

    Regression test for an incident where a stage's persisted attempt_count
    climbed past 70 over 12+ hours because nothing capped re-entry from
    outside a single _execute_with_retries call.
    """
    tenant, run, stages = _run_bundle()
    call_count = {"n": 0}

    async def always_fails(context: StageContext) -> StageOutcome:
        _ = context
        call_count["n"] += 1
        raise TransientError("still broken")

    handlers = default_noop_handlers(skip_communities=True)
    handlers[IngestionStageName.VALIDATE] = CallableStageHandler(
        IngestionStageName.VALIDATE, always_fails
    )
    orchestrator = IngestionOrchestrator(
        handlers,
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.0, jitter=False),
        sleep_fn=lambda _d: None,
    )

    # Simulate many separate dispatches of the same run against the same
    # persisted stage_records, each of which only ever sees up to 3 fresh
    # attempts internally.
    result = None
    for _ in range(10):
        result = await orchestrator.run(tenant=tenant, run=run, stage_records=stages)

    assert result is not None
    assert result.run_status is IngestionRunStatus.FAILED
    validate_stage = next(s for s in stages if s.stage is IngestionStageName.VALIDATE)
    assert validate_stage.attempt_count <= MAX_TOTAL_STAGE_ATTEMPTS
    # The handler itself must stop being invoked once the ceiling is hit --
    # proving this is a real circuit breaker, not just a status label.
    assert call_count["n"] <= MAX_TOTAL_STAGE_ATTEMPTS


@pytest.mark.asyncio
async def test_worker_processes_queue_and_persists_dead_letter() -> None:
    tenant, run, stages = _run_bundle()
    store = {"run": run, "stages": stages}

    async def boom(context: StageContext) -> StageOutcome:
        _ = context
        return StageOutcome(
            status=StageOutcomeStatus.FAILED,
            error_code="exhausted",
            error_message="still failing",
            retryable=True,
        )

    handlers = default_noop_handlers(skip_communities=True)
    handlers[IngestionStageName.VALIDATE] = CallableStageHandler(
        IngestionStageName.VALIDATE, boom
    )
    orchestrator = IngestionOrchestrator(
        handlers,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.0, jitter=False),
        sleep_fn=lambda _d: None,
    )
    queue = InMemoryIngestionTaskQueue()
    dead_letters = InMemoryDeadLetterStore()

    def load_run(_tenant: TenantContext, run_id: UUID) -> tuple[IngestionRunRecord, list]:
        assert run_id == store["run"].ingestion_run_id
        return store["run"], store["stages"]

    def persist_run(
        _tenant: TenantContext,
        updated_run: IngestionRunRecord,
        updated_stages: list,
    ) -> None:
        store["run"] = updated_run
        store["stages"] = updated_stages

    worker = IngestionWorker(
        queue=queue,
        dead_letter_store=dead_letters,
        orchestrator=orchestrator,
        load_run=load_run,
        persist_run=persist_run,
    )
    await queue.enqueue(
        IngestionTaskMessage(
            tenant_id=tenant.tenant_id,
            ingestion_run_id=run.ingestion_run_id,
            document_id=run.document_id,
            version_id=run.version_id,
            content_hash=run.content_hash or "",
            config_fingerprint=run.config_fingerprint or "",
        )
    )
    tick = await worker.process_one(timeout_seconds=0.1)
    assert tick.processed
    assert tick.result is not None
    assert tick.result.dead_letter is not None
    listed = await dead_letters.list_for_run(tenant, run.ingestion_run_id)
    assert len(listed) == 1
    assert isinstance(listed[0], DeadLetterRecord)
    assert store["run"].status is IngestionRunStatus.FAILED
    assert len(INGESTION_STAGE_ORDER) == 23
