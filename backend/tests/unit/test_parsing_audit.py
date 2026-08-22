"""Parsing audit collector, persistence, and comparison tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from graph_rag.application.ingestion.compare_parse_reports import (
    CompareParseReportsService,
    diff_snapshots,
)
from graph_rag.application.ingestion.parsing_audit_collector import ParsingAuditCollector
from graph_rag.domain.parsing.audit import (
    ContentLossReason,
    ElementProcessingStatus,
    RoutingReasonCode,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.parsing_audit import (
    InMemoryParsingAuditRepository,
)


def test_collector_tracks_detected_processed_and_loss() -> None:
    tenant_id = uuid4()
    doc_id = uuid4()
    version_id = uuid4()
    run_id = uuid4()
    collector = ParsingAuditCollector(
        tenant_id=tenant_id,
        document_id=doc_id,
        version_id=version_id,
        ingestion_run_id=run_id,
    )
    collector.document_started(original_filename="spec.pdf", mime_type="application/pdf")
    collector.record_routing(
        RoutingReasonCode.PRIMARY_PARSER_SELECTED,
        message="Docling selected",
        selected_tool="docling",
    )
    collector.stage_started("PARSE", tool="docling")
    ok = collector.element_detected(
        page_number=1,
        normalized_element_type="paragraph",
        detector="docling",
        parser_name="docling",
        reading_order=0,
    )
    lost = collector.element_detected(
        page_number=1,
        normalized_element_type="table",
        detector="docling",
        parser_name="docling",
        reading_order=1,
    )
    collector.element_processed(ok, processing_tool="normalizer")
    collector.element_failed(
        lost,
        failure_reason="TABLE_STRUCTURE_EXTRACTION_FAILED",
        error_code="TABLE_EXTRACTION_FAILED",
        content_loss_reason=ContentLossReason.PARSING_FAILURE,
    )
    collector.stage_completed("PARSE", output_count=2, error_count=1)
    collector.page_completed(1, page_parser="docling")
    snapshot = collector.document_completed(
        ingestion_status="completed_with_warnings",
        primary_parser="docling",
        total_pages=1,
        total_normalized_elements=1,
    )
    assert snapshot.document.total_detected_elements == 2
    assert snapshot.document.total_processed_elements == 1
    assert snapshot.document.total_failed_elements == 1
    assert len(snapshot.content_losses) == 1
    assert snapshot.content_losses[0].reason is ContentLossReason.PARSING_FAILURE
    assert snapshot.pages[0].element_type_counts["paragraph"] == 1
    assert snapshot.routing_decisions[0].reason_code is RoutingReasonCode.PRIMARY_PARSER_SELECTED


@pytest.mark.asyncio
async def test_memory_repo_immutable_and_compare() -> None:
    tenant = TenantContext(tenant_id=uuid4())
    doc_id = uuid4()
    version_id = uuid4()
    run_a = uuid4()
    run_b = uuid4()
    repo = InMemoryParsingAuditRepository()

    def _build(run_id, processed: int, parser: str):
        c = ParsingAuditCollector(
            tenant_id=tenant.tenant_id,
            document_id=doc_id,
            version_id=version_id,
            ingestion_run_id=run_id,
        )
        c.document_started(original_filename="a.pdf")
        for i in range(processed):
            el = c.element_detected(
                page_number=1,
                normalized_element_type="text",
                detector=parser,
                parser_name=parser,
                reading_order=i,
            )
            c.element_processed(el)
        if processed < 2:
            skipped = c.element_detected(
                page_number=1,
                normalized_element_type="equation",
                detector=parser,
                parser_name=parser,
                reading_order=99,
            )
            c.element_skipped(
                skipped,
                skip_reason="equation processing disabled",
                content_loss_reason=ContentLossReason.PROCESSING_DISABLED,
            )
        return c.document_completed(
            ingestion_status="completed",
            primary_parser=parser,
            parser_version="1.0" if run_id == run_a else "2.0",
            total_pages=1,
            total_normalized_elements=processed,
        )

    snap_a = _build(run_a, processed=2, parser="docling")
    snap_b = _build(run_b, processed=1, parser="mineru")
    await repo.save_snapshot(tenant, snap_a)
    await repo.save_snapshot(tenant, snap_b)
    runs = await repo.list_run_ids(tenant, document_id=doc_id)
    assert set(runs) == {run_a, run_b}

    diff = await CompareParseReportsService(repo).compare(
        tenant, document_id=doc_id, run_a=run_a, run_b=run_b
    )
    assert diff.document_deltas["primary_parser"]["changed"] is True
    assert diff.document_deltas["total_normalized_elements"]["run_a"] == 2
    assert diff.document_deltas["total_normalized_elements"]["run_b"] == 1
    assert any(item.get("change") == "missing_in_run_b" for item in diff.element_deltas) or any(
        item.get("change") == "added_in_run_b" for item in diff.element_deltas
    )


def test_diff_snapshots_detects_status_change() -> None:
    tenant_id = uuid4()
    doc_id = uuid4()
    version_id = uuid4()
    run_a = uuid4()
    run_b = uuid4()

    def base(run_id, status: ElementProcessingStatus):
        c = ParsingAuditCollector(
            tenant_id=tenant_id,
            document_id=doc_id,
            version_id=version_id,
            ingestion_run_id=run_id,
        )
        el = c.element_detected(
            page_number=2,
            normalized_element_type="table",
            detector="docling",
            parser_name="docling",
            reading_order=0,
        )
        if status is ElementProcessingStatus.PROCESSED:
            c.element_processed(el)
        else:
            c.element_failed(el, failure_reason="boom")
        return c.document_completed(ingestion_status="completed", primary_parser="docling")

    a = base(run_a, ElementProcessingStatus.PROCESSED)
    b = base(run_b, ElementProcessingStatus.FAILED)
    diff = diff_snapshots(document_id=doc_id, run_a=run_a, run_b=run_b, a=a, b=b)
    assert any(item.get("change") == "modified" for item in diff.element_deltas)
