"""Ingestion state machine unit tests."""

from __future__ import annotations

import pytest

from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.ingestion import (
    INGESTION_STAGE_ORDER,
    IngestionRunStatus,
    IngestionStageName,
    IngestionStateMachine,
    StageStatus,
    build_persisted_stage_records,
)
from graph_rag.shared.exceptions import IngestionError


def test_pipeline_has_twenty_two_stages() -> None:
    assert len(INGESTION_STAGE_ORDER) == 22
    assert INGESTION_STAGE_ORDER[0] is IngestionStageName.VALIDATE
    assert INGESTION_STAGE_ORDER[-1] is IngestionStageName.FINALIZE


def test_idempotency_key_is_stable() -> None:
    tenant_id = new_id()
    version_id = new_id()
    content_hash = content_sha256_hex("doc")
    first = IngestionStateMachine.build_idempotency_key(
        tenant_id=tenant_id,
        version_id=version_id,
        stage=IngestionStageName.PARSE,
        config_fingerprint="fp-1",
        content_hash=content_hash,
    )
    second = IngestionStateMachine.build_idempotency_key(
        tenant_id=tenant_id,
        version_id=version_id,
        stage=IngestionStageName.PARSE,
        config_fingerprint="fp-1",
        content_hash=content_hash.upper(),
    )
    assert first == second
    assert len(first) == 64


def test_mark_running_requires_predecessors() -> None:
    machine = IngestionStateMachine()
    key = "k"
    fp = "fp"
    with pytest.raises(IngestionError, match="Predecessor"):
        machine.mark_running(IngestionStageName.HASH, idempotency_key=key, config_fingerprint=fp)


def test_happy_path_progress_and_finalize_gate() -> None:
    machine = IngestionStateMachine()
    key = "k"
    fp = "fp"
    for stage in INGESTION_STAGE_ORDER:
        if stage is IngestionStageName.FINALIZE:
            assert machine.can_finalize()
        machine.mark_running(stage, idempotency_key=key, config_fingerprint=fp)
        if stage is IngestionStageName.SUMMARIZE_COMMUNITIES:
            machine.mark_skipped(stage, reason="disabled")
        else:
            warning = "low ocr" if stage is IngestionStageName.PARSE else None
            machine.mark_completed(stage, warning=warning)

    assert machine.run_status is IngestionRunStatus.COMPLETED_WITH_WARNINGS
    progress = machine.progress()
    assert progress.estimated_completion_percent == 100.0
    assert progress.current_stage is None
    assert IngestionStageName.VALIDATE in progress.completed_stages


def test_resume_skip_when_fingerprint_matches() -> None:
    machine = IngestionStateMachine()
    key = IngestionStateMachine.build_idempotency_key(
        tenant_id="t",
        version_id="v",
        stage=IngestionStageName.VALIDATE,
        config_fingerprint="fp",
        content_hash="a" * 64,
    )
    machine.mark_running(
        IngestionStageName.VALIDATE,
        idempotency_key=key,
        config_fingerprint="fp",
    )
    machine.mark_completed(IngestionStageName.VALIDATE)
    assert machine.should_skip_on_resume(
        IngestionStageName.VALIDATE,
        idempotency_key=key,
        config_fingerprint="fp",
    )
    assert not machine.should_skip_on_resume(
        IngestionStageName.VALIDATE,
        idempotency_key=key,
        config_fingerprint="fp-changed",
    )


def test_cancel_marks_pending_stages() -> None:
    machine = IngestionStateMachine()
    machine.mark_running(
        IngestionStageName.VALIDATE,
        idempotency_key="k",
        config_fingerprint="fp",
    )
    machine.cancel()
    assert machine.run_status is IngestionRunStatus.CANCELLED
    assert machine.get_stage(IngestionStageName.VALIDATE).status is StageStatus.CANCELLED
    assert machine.get_stage(IngestionStageName.HASH).status is StageStatus.CANCELLED


def test_build_persisted_stage_records_count() -> None:
    records = build_persisted_stage_records(
        tenant_id=new_id(),
        ingestion_run_id=new_id(),
    )
    assert len(records) == 22
    assert records[0].stage is IngestionStageName.VALIDATE
    assert records[0].status is StageStatus.PENDING
