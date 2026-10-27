"""Derived progress_state from run status and heartbeat."""

from datetime import UTC, datetime, timedelta

from graph_rag.application.ingestion.progress import derive_progress_state, last_completed_stage
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.records import IngestionStageRecord
from graph_rag.domain.ingestion.stages import IngestionStageName, StageStatus


def test_stalled_when_heartbeat_is_old_or_missing() -> None:
    now = datetime.now(UTC)
    assert derive_progress_state("running", None, now=now) == "stalled"
    assert (
        derive_progress_state("pending", now - timedelta(seconds=121), now=now) == "stalled"
    )
    assert derive_progress_state("running", now - timedelta(seconds=10), now=now) == "running"


def test_terminal_statuses_map() -> None:
    now = datetime.now(UTC)
    assert derive_progress_state("completed", now, now=now) == "ready"
    assert derive_progress_state("completed_with_warnings", None, now=now) == "ready"
    assert derive_progress_state("partial", now, now=now) == "partial"
    assert derive_progress_state("failed", now, now=now) == "failed"
    assert derive_progress_state("cancelled", now, now=now) == "cancelled"


def test_last_completed_stage_is_included() -> None:
    tenant = new_id()
    run = new_id()
    stages = [
        IngestionStageRecord(
            stage_id=new_id(),
            tenant_id=tenant,
            ingestion_run_id=run,
            stage=IngestionStageName.VALIDATE,
            status=StageStatus.COMPLETED,
        ),
        IngestionStageRecord(
            stage_id=new_id(),
            tenant_id=tenant,
            ingestion_run_id=run,
            stage=IngestionStageName.HASH,
            status=StageStatus.PENDING,
        ),
    ]
    assert last_completed_stage(stages) == "VALIDATE"
