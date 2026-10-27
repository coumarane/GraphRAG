"""A worker crash before ack leaves the Redis message for the next worker."""

from __future__ import annotations

from uuid import uuid4

import pytest
import redis.asyncio as redis_async

from graph_rag.application.ingestion.orchestrator import OrchestrationResult
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.ingestion.retry import IngestionTaskMessage
from graph_rag.domain.ingestion.stages import (
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
)
from graph_rag.domain.ingestion.state_machine import (
    IngestionProgress,
    build_persisted_stage_records,
)
from graph_rag.infrastructure.persistence.dead_letters import InMemoryDeadLetterStore
from graph_rag.infrastructure.persistence.redis.streams import RedisStreamIngestionQueue
from graph_rag.infrastructure.workers import IngestionWorker


def _progress(status: IngestionRunStatus) -> IngestionProgress:
    return IngestionProgress(
        current_stage=IngestionStageName.VALIDATE,
        completed_stages=[],
        pages_processed=0,
        elements_processed=0,
        estimated_completion_percent=1.0,
        retry_count=0,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restarted_worker_finishes_the_unacked_run(compose_redis: str) -> None:
    client = redis_async.from_url(compose_redis, decode_responses=False)
    stream = f"crash-{uuid4().hex}"
    queue = RedisStreamIngestionQueue(
        client,
        stream_key=stream,
        group_name="workers",
        consumer_name="worker-a",
    )
    tenant_id = new_id()
    run_id = new_id()
    run = IngestionRunRecord(
        ingestion_run_id=run_id,
        tenant_id=tenant_id,
        document_id=new_id(),
        version_id=new_id(),
        content_hash="b" * 64,
        config_fingerprint="fp-v1",
        status=IngestionRunStatus.PENDING,
    )
    stages = build_persisted_stage_records(tenant_id=tenant_id, ingestion_run_id=run_id)
    calls = {"count": 0}

    async def pipeline(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            kwargs["run"].status = IngestionRunStatus.RUNNING
            kwargs["stages"][0].status = StageStatus.RUNNING
            return OrchestrationResult(
                run_status=IngestionRunStatus.RUNNING,
                progress=_progress(IngestionRunStatus.RUNNING),
            )
        kwargs["run"].status = IngestionRunStatus.COMPLETED
        return OrchestrationResult(
            run_status=IngestionRunStatus.COMPLETED,
            progress=_progress(IngestionRunStatus.COMPLETED),
        )

    async def persist(_tenant, updated, rows) -> None:
        nonlocal run, stages
        run = updated
        stages = rows

    first = IngestionWorker(
        queue=queue,
        dead_letter_store=InMemoryDeadLetterStore(),
        load_run=lambda _t, _id: (run, stages),
        persist_run=persist,
        run_pipeline=pipeline,
        worker_id="worker-a",
        reclaim_idle_seconds=0,
        heartbeat_stale_seconds=0,
    )
    await queue.enqueue(
        IngestionTaskMessage(
            tenant_id=tenant_id,
            ingestion_run_id=run_id,
            document_id=run.document_id,
            version_id=run.version_id,
            content_hash=run.content_hash or "",
            config_fingerprint=run.config_fingerprint or "",
        )
    )
    crashed = await first.process_one(timeout_seconds=0.2)
    assert crashed.processed
    assert crashed.acknowledged is False
    assert await queue.pending_count() == 1

    second = IngestionWorker(
        queue=RedisStreamIngestionQueue(
            client,
            stream_key=stream,
            group_name="workers",
            consumer_name="worker-b",
        ),
        dead_letter_store=InMemoryDeadLetterStore(),
        load_run=lambda _t, _id: (run, stages),
        persist_run=persist,
        run_pipeline=pipeline,
        worker_id="worker-b",
        reclaim_idle_seconds=0,
        heartbeat_stale_seconds=0,
    )
    finished = await second.process_one(timeout_seconds=0.2)
    assert finished.processed
    assert finished.acknowledged
    assert run.status is IngestionRunStatus.COMPLETED
    assert await queue.pending_count() == 0
    await client.aclose()
