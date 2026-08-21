"""Per-page/per-element parse audit recording in the resumable stage pipeline.

The parsing audit collector (page/element detail shown in the "Parse
report" UI) has always had methods for this, but the resumable worker
pipeline (stage_pipeline.py) never called them — only the older, separate
in-process pipeline (local_pipeline.py) did. Real documents processed
through the production worker path ended up with an accurate document-level
summary (page/element counts, durations) but empty `pages`/`elements`
arrays. These tests cover the fix directly, without needing a full parser
or worker harness.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from enterprise_rag.application.ingestion.parsing_audit_collector import ParsingAuditCollector
from enterprise_rag.application.ingestion.stage_pipeline import DocumentPipeline, PipelineWorkspace
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.elements.geometry import BoundingBox
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.ingestion.handlers import StageContext
from enterprise_rag.domain.parsing.audit import ElementProcessingStatus
from enterprise_rag.domain.parsing.normalize import normalize_parser_result
from enterprise_rag.domain.parsing.types import ParseSource, RawElement, RawPage, RawParserResult
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore


def _workspace() -> PipelineWorkspace:
    # _record_parse_audit only touches workspace.audit; the `service` arg
    # exists purely to satisfy PipelineWorkspace's constructor.
    workspace = PipelineWorkspace(service=None)  # type: ignore[arg-type]
    workspace.audit = ParsingAuditCollector(
        tenant_id=new_id(),
        document_id=new_id(),
        version_id=new_id(),
        ingestion_run_id=new_id(),
    )
    return workspace


def _raw_result() -> RawParserResult:
    return RawParserResult(
        parser_name="docling",
        page_count=2,
        pages=[
            RawPage(page_number=1, is_scanned=False),
            RawPage(page_number=2, is_scanned=True),
        ],
        elements=[
            RawElement(
                element_type=ElementType.TEXT,
                page_start=1,
                page_end=1,
                reading_order=0,
                normalized_content="Intro paragraph.",
                bounding_boxes=[BoundingBox(page_number=1, x0=0.0, y0=0.0, x1=1.0, y1=1.0)],
                parser_confidence=0.95,
            ),
            RawElement(
                element_type=ElementType.IMAGE,
                page_start=1,
                page_end=1,
                reading_order=1,
                raw_content="[image]",
            ),
            RawElement(
                element_type=ElementType.TABLE,
                page_start=2,
                page_end=2,
                reading_order=0,
                normalized_content="| a | b |",
            ),
        ],
    )


def test_record_parse_audit_populates_pages_and_elements() -> None:
    workspace = _workspace()
    pipeline = DocumentPipeline(workspace)

    pipeline._record_parse_audit(_raw_result(), primary="docling")

    assert len(workspace.audit._elements) == 3
    assert {el.normalized_element_type for el in workspace.audit._elements} == {
        "text",
        "image",
        "table",
    }
    assert all(el.detector == "docling" for el in workspace.audit._elements)
    text_element = next(
        el for el in workspace.audit._elements if el.normalized_element_type == "text"
    )
    assert text_element.confidence_score == 0.95
    assert text_element.bbox == {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}

    assert set(workspace.audit._pages.keys()) == {1, 2}
    page_one = workspace.audit._pages[1]
    assert page_one.detected_elements == 2
    assert page_one.element_type_counts == {"text": 1, "image": 1}
    assert page_one.has_native_text is True
    assert page_one.ocr_required is False

    page_two = workspace.audit._pages[2]
    assert page_two.detected_elements == 1
    assert page_two.has_native_text is False
    assert page_two.ocr_required is True


def test_record_parse_audit_handles_empty_document() -> None:
    workspace = _workspace()
    pipeline = DocumentPipeline(workspace)

    pipeline._record_parse_audit(
        RawParserResult(parser_name="docling", page_count=0), primary="docling"
    )

    assert workspace.audit._elements == []
    assert workspace.audit._pages == {}


def test_reconcile_normalized_audit_clears_false_content_loss() -> None:
    """Without reconciliation, every detected element stays reached_normalized=False,
    and reconcile_content_loss() (run at document_completed) flags all of them as
    lost content — even for documents that processed successfully end to end. This
    is a regression test for that false-positive: after normalization runs, every
    element that survived should be marked PROCESSED / reached_normalized=True.
    """
    workspace = _workspace()
    pipeline = DocumentPipeline(workspace)
    raw = _raw_result()
    pipeline._record_parse_audit(raw, primary="docling")
    assert all(not el.reached_normalized for el in workspace.audit._elements)

    source = ParseSource(
        tenant_id=workspace.audit.tenant_id,
        document_id=workspace.audit.document_id,
        version_id=workspace.audit.version_id,
        filename="doc.pdf",
        mime_type="application/pdf",
        content=b"%PDF-1.4",
    )
    normalized = normalize_parser_result(raw, source)

    pipeline._reconcile_normalized_audit(normalized)

    assert workspace.audit._elements
    assert all(el.reached_normalized for el in workspace.audit._elements)
    assert all(el.status == ElementProcessingStatus.PROCESSED for el in workspace.audit._elements)
    assert all(el.element_id is not None for el in workspace.audit._elements)

    workspace.audit.reconcile_content_loss()
    assert workspace.audit.content_losses == []


@pytest.mark.asyncio
async def test_reprocess_resuming_from_cached_artifacts_still_records_audit() -> None:
    """parse_raw/normalized/chunks/embeddings artifacts are cached by
    (tenant, document, version) only, not by run_id — the CACHE IS SHARED across
    reprocesses of the same document version. A reprocess run's own fresh audit
    collector must still get populated from that cache, or every reprocess (the
    common case, not a rare edge case) would silently produce an empty Parse
    Report exactly like the original bug this file guards against.
    """
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    tenant = TenantContext(tenant_id=tenant_id)
    object_store = InMemoryObjectStore()
    run_stub = SimpleNamespace(document_id=document_id, version_id=version_id)
    version_stub = SimpleNamespace(
        mime_type="application/pdf", content_hash="0" * 64, byte_size=8
    )
    service_stub = SimpleNamespace(
        object_store=object_store, chat_model=None, embedding_model=None
    )

    # First run: parses for real and writes parse_raw/normalized to the shared
    # object store, exactly like stage_parse/stage_normalize do.
    raw = _raw_result()
    first_run_id = new_id()
    w1 = PipelineWorkspace(service=service_stub)  # type: ignore[arg-type]
    w1.tenant = tenant
    w1.run = run_stub
    w1.audit = ParsingAuditCollector(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        ingestion_run_id=first_run_id,
    )
    pipeline1 = DocumentPipeline(w1)
    pipeline1._record_parse_audit(raw, primary="docling")
    await w1.save_json(
        "parse_raw",
        {
            "raw": raw.model_dump(mode="json"),
            "selected_parser": "docling",
            "used_parser": "docling",
            "attempted": ["docling"],
            "fallbacks": [],
            "vision_failed": 0,
            "vision_target_count": 0,
        },
    )
    source = ParseSource(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        filename="doc.pdf",
        mime_type="application/pdf",
        content=b"%PDF-1.4",
    )
    normalized = normalize_parser_result(raw, source)
    pipeline1._reconcile_normalized_audit(normalized)
    await w1.save_json("normalized", normalized.model_dump(mode="json"))

    # Second run (a reprocess): fresh workspace/audit, same document+version,
    # so it resumes from the artifacts the first run cached above.
    second_run_id = new_id()
    w2 = PipelineWorkspace(service=service_stub)  # type: ignore[arg-type]
    w2.tenant = tenant
    w2.run = run_stub
    w2.version = version_stub
    w2.document = SimpleNamespace()
    w2.data = b"%PDF-1.4"
    w2.filename = "doc.pdf"
    w2.mime = "application/pdf"
    pipeline2 = DocumentPipeline(w2)
    context = StageContext(
        tenant=tenant,
        ingestion_run_id=second_run_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="0" * 64,
        config_fingerprint="test",
    )

    await pipeline2.ensure_loaded(context)

    assert w2.audit is not None
    assert len(w2.audit._elements) == 3
    assert all(el.reached_normalized for el in w2.audit._elements)
    assert all(el.status == ElementProcessingStatus.PROCESSED for el in w2.audit._elements)
    w2.audit.reconcile_content_loss()
    assert w2.audit.content_losses == []
