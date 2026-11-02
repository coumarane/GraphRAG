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
    assert len(INGESTION_STAGE_ORDER) == 23
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


def _finish_run(
    machine: IngestionStateMachine,
    *,
    warnings: dict[IngestionStageName, str] | None = None,
    skips: dict[IngestionStageName, str] | None = None,
) -> None:
    warnings = warnings or {}
    skips = skips or {}
    for stage in INGESTION_STAGE_ORDER:
        machine.mark_running(stage, idempotency_key="k", config_fingerprint="fp")
        if stage is IngestionStageName.FINALIZE:
            machine.mark_completed(stage, warning=warnings.get(stage))
        elif stage in skips:
            machine.mark_skipped(stage, reason=skips[stage])
        else:
            machine.mark_completed(stage, warning=warnings.get(stage))


def test_skip_only_run_completes_without_a_latest_warning() -> None:
    machine = IngestionStateMachine()
    skips = {
        stage: "community summarization disabled"
        if stage is IngestionStageName.SUMMARIZE_COMMUNITIES
        else "handled in parse"
        for stage in INGESTION_STAGE_ORDER
        if stage is not IngestionStageName.FINALIZE
    }
    skips[IngestionStageName.EXTRACT_DOCUMENT_INTELLIGENCE] = "document_intelligence not requested"
    skips[IngestionStageName.EXTRACT_GRAPH] = "graph store disabled"
    _finish_run(machine, skips=skips)
    assert machine.run_status is IngestionRunStatus.COMPLETED
    assert machine.progress().latest_warning is None
    assert (
        machine.get_stage(IngestionStageName.SUMMARIZE_COMMUNITIES).warning
        == "community summarization disabled"
    )
    assert machine.get_stage(IngestionStageName.SUMMARIZE_COMMUNITIES).status is StageStatus.SKIPPED


def test_semantic_graph_failure_is_a_run_warning() -> None:
    machine = IngestionStateMachine()
    _finish_run(
        machine,
        warnings={IngestionStageName.EXTRACT_GRAPH: "semantic_graph_failed:RuntimeError"},
        skips={IngestionStageName.SUMMARIZE_COMMUNITIES: "community summarization disabled"},
    )
    assert machine.run_status is IngestionRunStatus.COMPLETED_WITH_WARNINGS
    assert machine.progress().latest_warning == "semantic_graph_failed:RuntimeError"


def test_document_intelligence_miss_counts_without_a_prefix_list() -> None:
    machine = IngestionStateMachine()
    warning = "document_intelligence: missing=batch_code"
    _finish_run(
        machine,
        warnings={IngestionStageName.EXTRACT_DOCUMENT_INTELLIGENCE: warning},
        skips={IngestionStageName.SUMMARIZE_COMMUNITIES: "community summarization disabled"},
    )
    assert machine.run_status is IngestionRunStatus.COMPLETED_WITH_WARNINGS
    assert machine.progress().latest_warning == warning


def test_build_persisted_stage_records_count() -> None:
    records = build_persisted_stage_records(
        tenant_id=new_id(),
        ingestion_run_id=new_id(),
    )
    assert len(records) == 23
    assert records[0].stage is IngestionStageName.VALIDATE
    assert records[0].status is StageStatus.PENDING
