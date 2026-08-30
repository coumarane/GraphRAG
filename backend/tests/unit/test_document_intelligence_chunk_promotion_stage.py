"""Chunk/Qdrant field promotion through the real stage handlers (Phase 9).

Runs ``stage_extract_document_intelligence`` then ``stage_chunk`` in sequence
against a real two-page document, mirroring
``test_document_intelligence_reuse_stage.py``'s direct-stage-construction
pattern. Verifies the design doc's own test requirement: "promoted fields
appear in [chunk/Qdrant] metadata only when configured."
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceIngestOptions,
    ExtractedFieldResult,
    ExtractionMethod,
    FieldType,
    ModelFieldSpec,
    confidence_band,
)
from graph_rag.application.ingestion import stage_pipeline as stage_pipeline_module
from graph_rag.application.ingestion.parsing_audit_collector import ParsingAuditCollector
from graph_rag.application.ingestion.stage_pipeline import DocumentPipeline, PipelineWorkspace
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.handlers import StageContext
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.parsing.normalize import normalize_parser_result
from graph_rag.domain.parsing.types import ParseSource, RawElement, RawPage, RawParserResult
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.document_intelligence import (
    InMemoryDocumentExtractionRepository,
)


class _FakeProvider:
    """Returns one ``ExtractedFieldResult`` per requested field, with a fixed page map."""

    def __init__(self, pages_by_name: dict[str, int | None]) -> None:
        self._pages_by_name = pages_by_name

    async def extract(self, request):
        names = [field.name for field in request.fields]
        fields = [
            ExtractedFieldResult(
                name=name,
                value=f"value-{name}",
                confidence=0.8,
                confidence_band=confidence_band(0.8),
                extraction_method=ExtractionMethod.RULES,
                page=self._pages_by_name.get(name),
            )
            for name in names
        ]
        return stage_pipeline_module.DocumentIntelligenceExtractionResult(
            fields=fields, requested_field_names=names, unresolved_field_names=[]
        )


def _raw_result() -> RawParserResult:
    return RawParserResult(
        parser_name="test",
        page_count=2,
        pages=[RawPage(page_number=1), RawPage(page_number=2)],
        elements=[
            RawElement(
                element_type=ElementType.TEXT,
                page_start=1,
                page_end=1,
                reading_order=0,
                section_path=["Section A"],
                normalized_content="Page one content about the first topic in enough detail.",
            ),
            RawElement(
                element_type=ElementType.TEXT,
                page_start=2,
                page_end=2,
                reading_order=0,
                section_path=["Section B"],
                normalized_content="Page two content about a completely different topic.",
            ),
        ],
    )


async def _run_stages(*, custom_fields: list[ModelFieldSpec], pages_by_name: dict[str, int | None]):
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    document_id = new_id()
    version_id = new_id()
    ingestion_run_id = new_id()

    source = ParseSource(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        filename="doc.pdf",
        mime_type="application/pdf",
    )
    raw = _raw_result()
    normalized = normalize_parser_result(raw, source)

    provider = _FakeProvider(pages_by_name)
    extraction_repo = InMemoryDocumentExtractionRepository()
    built = build_local_container(
        document_intelligence_provider=provider,  # type: ignore[arg-type]
        document_extraction_repo=extraction_repo,
    )
    service = built.require_process_ingestion()

    options = DocumentIntelligenceIngestOptions(enabled=True, custom_fields=custom_fields)
    run = IngestionRunRecord(
        ingestion_run_id=ingestion_run_id,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
        metadata={"document_intelligence": options.model_dump(mode="json")},
    )
    workspace = PipelineWorkspace(service=service)
    workspace.tenant = tenant
    workspace.run = run
    workspace.version = SimpleNamespace(content_hash="hash-v1")
    workspace.document = SimpleNamespace(title="Doc Title")
    workspace.audit = ParsingAuditCollector(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        ingestion_run_id=ingestion_run_id,
    )
    workspace.data = b"%PDF-1.4\nplaceholder\n%%EOF\n"
    workspace.filename = "doc.pdf"
    workspace.raw = raw
    workspace.normalized = normalized

    context = StageContext(
        tenant=tenant,
        ingestion_run_id=ingestion_run_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
    )
    pipeline = DocumentPipeline(workspace)
    await pipeline.stage_extract_document_intelligence(context)
    await pipeline.stage_chunk(context)
    return workspace


@pytest.mark.asyncio
async def test_document_level_promoted_field_appears_on_every_chunk() -> None:
    workspace = await _run_stages(
        custom_fields=[
            ModelFieldSpec(
                name="doc_field",
                label="Doc field",
                field_type=FieldType.STRING,
                promote_to_document_metadata=True,
            ),
        ],
        pages_by_name={"doc_field": None},
    )
    assert len(workspace.chunks) > 0
    for chunk in workspace.chunks:
        assert chunk.metadata.get("document_intelligence", {}).get("doc_field") == "value-doc_field"


@pytest.mark.asyncio
async def test_page_scoped_promoted_field_only_on_chunks_covering_that_page() -> None:
    workspace = await _run_stages(
        custom_fields=[
            ModelFieldSpec(
                name="page_field",
                label="Page field",
                field_type=FieldType.STRING,
                promote_to_document_metadata=True,
            ),
        ],
        pages_by_name={"page_field": 2},
    )
    assert len(workspace.chunks) > 0
    for chunk in workspace.chunks:
        covers_page_2 = chunk.page_start <= 2 <= chunk.page_end
        present = "page_field" in chunk.metadata.get("document_intelligence", {})
        assert present == covers_page_2


@pytest.mark.asyncio
async def test_non_promoted_field_never_appears_in_chunk_metadata() -> None:
    workspace = await _run_stages(
        custom_fields=[
            ModelFieldSpec(
                name="not_promoted",
                label="Not promoted",
                field_type=FieldType.STRING,
                promote_to_document_metadata=False,
            ),
        ],
        pages_by_name={"not_promoted": None},
    )
    assert len(workspace.chunks) > 0
    for chunk in workspace.chunks:
        assert "document_intelligence" not in chunk.metadata


@pytest.mark.asyncio
async def test_di_not_requested_leaves_chunk_metadata_unchanged() -> None:
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    document_id = new_id()
    version_id = new_id()
    ingestion_run_id = new_id()
    source = ParseSource(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        filename="doc.pdf",
        mime_type="application/pdf",
    )
    raw = _raw_result()
    normalized = normalize_parser_result(raw, source)
    provider = _FakeProvider({})
    built = build_local_container(
        document_intelligence_provider=provider,  # type: ignore[arg-type]
        document_extraction_repo=InMemoryDocumentExtractionRepository(),
    )
    service = built.require_process_ingestion()
    run = IngestionRunRecord(
        ingestion_run_id=ingestion_run_id,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
        metadata={},
    )
    workspace = PipelineWorkspace(service=service)
    workspace.tenant = tenant
    workspace.run = run
    workspace.version = SimpleNamespace(content_hash="hash-v1")
    workspace.document = SimpleNamespace(title="Doc Title")
    workspace.audit = ParsingAuditCollector(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        ingestion_run_id=ingestion_run_id,
    )
    workspace.data = b"%PDF-1.4\nplaceholder\n%%EOF\n"
    workspace.filename = "doc.pdf"
    workspace.raw = raw
    workspace.normalized = normalized
    context = StageContext(
        tenant=tenant,
        ingestion_run_id=ingestion_run_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
    )
    pipeline = DocumentPipeline(workspace)
    outcome = await pipeline.stage_extract_document_intelligence(context)
    assert outcome.status.value == "skipped"
    await pipeline.stage_chunk(context)
    assert len(workspace.chunks) > 0
    for chunk in workspace.chunks:
        assert "document_intelligence" not in chunk.metadata
        assert chunk.metadata.get("document_name") == "Doc Title"
