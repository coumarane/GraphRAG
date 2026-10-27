"""Completed stages stay completed, and exhausted retries become one dead letter."""

from __future__ import annotations

import pytest

from graph_rag.application.ingestion.handlers import CallableStageHandler, default_noop_handlers
from graph_rag.application.ingestion.orchestrator import IngestionOrchestrator
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.handlers import StageContext, StageOutcome, StageOutcomeStatus
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.ingestion.retry import RetryPolicy
from graph_rag.domain.ingestion.stages import (
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
)
from graph_rag.domain.ingestion.state_machine import (
    IngestionStateMachine,
    build_persisted_stage_records,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import TransientError


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resume_skips_completed_and_dead_letters_at_bound() -> None:
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    run_id = new_id()
    stages = build_persisted_stage_records(tenant_id=tenant.tenant_id, ingestion_run_id=run_id)
    version_id = new_id()
    stages[0].status = StageStatus.COMPLETED
    stages[0].config_fingerprint = "intake-v1"
    stages[0].idempotency_key = IngestionStateMachine.build_idempotency_key(
        tenant_id=tenant.tenant_id,
        version_id=version_id,
        stage=IngestionStageName.VALIDATE,
        config_fingerprint="intake-v1",
        content_hash="a" * 64,
    )
    hash_calls = 0
    validate_calls = 0

    async def fail_hash(_context: StageContext) -> StageOutcome:
        nonlocal hash_calls
        hash_calls += 1
        raise TransientError("temporary")

    async def count_validate(_context: StageContext) -> StageOutcome:
        nonlocal validate_calls
        validate_calls += 1
        return StageOutcome(status=StageOutcomeStatus.COMPLETED)

    handlers = default_noop_handlers(skip_communities=True)
    handlers[IngestionStageName.VALIDATE] = CallableStageHandler(
        IngestionStageName.VALIDATE, count_validate
    )
    handlers[IngestionStageName.HASH] = CallableStageHandler(IngestionStageName.HASH, fail_hash)
    orchestrator = IngestionOrchestrator(
        handlers,
        retry_policy=RetryPolicy(max_attempts=3, jitter=False),
        sleep_fn=_no_sleep,
    )
    run = IngestionRunRecord(
        ingestion_run_id=run_id,
        tenant_id=tenant.tenant_id,
        document_id=new_id(),
        version_id=version_id,
        status=IngestionRunStatus.PENDING,
        content_hash="a" * 64,
        config_fingerprint="intake-v1",
    )
    result = await orchestrator.run(tenant=tenant, run=run, stage_records=stages)
    assert validate_calls == 0
    assert stages[0].status is StageStatus.COMPLETED
    assert hash_calls == 3
    assert result.dead_letter is not None
    assert result.dead_letter.tenant_id == tenant.tenant_id
    assert result.dead_letter.ingestion_run_id == run_id
    assert result.dead_letter.stage is IngestionStageName.HASH
    assert result.dead_letter.error_code


async def _no_sleep(_delay: float) -> None:
    return None
