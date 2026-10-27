"""A run with no fresh heartbeat is stalled and still names the last completed step."""

from datetime import UTC, datetime, timedelta

import pytest

from graph_rag.api.routes.ingestion import _run_response
from graph_rag.application.ingestion.progress import derive_progress_state, last_completed_stage
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.ingestion.stages import IngestionRunStatus, StageStatus
from graph_rag.domain.ingestion.state_machine import build_persisted_stage_records


@pytest.mark.integration
def test_stopped_worker_is_stalled_with_last_completed_stage() -> None:
    tenant_id = new_id()
    run_id = new_id()
    stages = build_persisted_stage_records(tenant_id=tenant_id, ingestion_run_id=run_id)
    stages[0].status = StageStatus.COMPLETED
    state = derive_progress_state(
        "running",
        datetime.now(UTC) - timedelta(seconds=121),
    )
    assert state == "stalled"
    assert last_completed_stage(stages) == "VALIDATE"
    run = IngestionRunRecord(
        ingestion_run_id=run_id,
        tenant_id=tenant_id,
        document_id=new_id(),
        version_id=new_id(),
        status=IngestionRunStatus.RUNNING,
        heartbeat_at=datetime.now(UTC) - timedelta(seconds=121),
    )
    body = _run_response(run, stages)
    assert body.progress_state == "stalled"
    assert body.last_completed_stage == "VALIDATE"
