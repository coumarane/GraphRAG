"""Regression test for the reindex-with-DI stale-artifact-cache bug.

``PipelineWorkspace.ensure_loaded`` rehydrates ``w.chunks``/``w.embedded``
from object-store artifacts keyed only by ``(tenant, document, version)`` --
not ``ingestion_run_id``. ``stage_chunk`` short-circuits unconditionally
(``if w.chunks: return COMPLETED``) whenever that artifact already exists.
Resuming a reindex at ``EXTRACT_DOCUMENT_INTELLIGENCE`` without clearing this
cache would silently never re-attach newly-promoted fields -- the reindex
would "succeed" and do nothing. This is a real bug the ``DOCUMENT_INTELLIGENCE``
reindex scope in ``application/deletion/reindex.py`` fixes by deleting the
``chunks``/``embeddings``/``graph`` artifact keys before resuming (but never
``parse_raw``/``normalized``, since no re-parse is needed).

This test reproduces the bug on a fresh workspace/run sharing a
previously-chunked document version, then proves that clearing the artifact
(the same operation ``ReindexDocumentService`` performs) makes ``stage_chunk``
redo its work and attach the newly-promoted field.
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
from graph_rag.application.ingestion.stage_pipeline import (
    DocumentPipeline,
    PipelineWorkspace,
    artifact_key,
)
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
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    async def extract(self, request):
        names = [field.name for field in request.fields]
        fields = [
            ExtractedFieldResult(
                name=name,
                value=self._values[name],
                confidence=0.8,
                confidence_band=confidence_band(0.8),
                extraction_method=ExtractionMethod.RULES,
            )
            for name in names
            if name in self._values
        ]
        return stage_pipeline_module.DocumentIntelligenceExtractionResult(
            fields=fields,
            requested_field_names=names,
            unresolved_field_names=[name for name in names if name not in self._values],
        )


def _raw_and_normalized(tenant_id, document_id, version_id):
    raw = RawParserResult(
        parser_name="test",
        page_count=1,
        pages=[RawPage(page_number=1)],
        elements=[
            RawElement(
                element_type=ElementType.TEXT,
                page_start=1,
                page_end=1,
                reading_order=0,
                normalized_content="Some page content for chunking.",
            ),
        ],
    )
    source = ParseSource(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        filename="doc.pdf",
        mime_type="application/pdf",
    )
    normalized = normalize_parser_result(raw, source)
    return raw, normalized


async def _seeded_workspace(service, *, tenant, document_id, version_id, ingestion_run_id, options):
    """Build a workspace and persist parse_raw/normalized artifacts for real."""
    raw, normalized = _raw_and_normalized(tenant.tenant_id, document_id, version_id)
    run = IngestionRunRecord(
        ingestion_run_id=ingestion_run_id,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
        metadata={"document_intelligence": options.model_dump(mode="json")} if options else {},
    )
    workspace = PipelineWorkspace(service=service)
    workspace.tenant = tenant
    workspace.run = run
    workspace.version = SimpleNamespace(
        content_hash="hash-v1", mime_type="application/pdf", byte_size=100
    )
    workspace.document = SimpleNamespace(title="Doc Title")
    workspace.data = b"%PDF-1.4\nplaceholder\n%%EOF\n"
    workspace.filename = "doc.pdf"
    workspace.raw = raw
    workspace.normalized = normalized
    await workspace.save_json(
        "parse_raw",
        {
            "raw": raw.model_dump(mode="json"),
            "selected_parser": "test",
            "used_parser": "test",
            "attempted": [],
            "fallbacks": [],
            "vision_failed": 0,
            "vision_target_count": 0,
            "vision_done": True,
        },
    )
    await workspace.save_json("normalized", normalized.model_dump(mode="json"))
    return workspace


def _fresh_workspace(service, *, tenant, document_id, version_id, ingestion_run_id, options):
    """A workspace with nothing pre-set, forcing ensure_loaded's cache path."""
    run = IngestionRunRecord(
        ingestion_run_id=ingestion_run_id,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
        metadata={"document_intelligence": options.model_dump(mode="json")} if options else {},
    )
    workspace = PipelineWorkspace(service=service)
    workspace.tenant = tenant
    workspace.run = run
    workspace.version = SimpleNamespace(
        content_hash="hash-v1", mime_type="application/pdf", byte_size=100
    )
    workspace.document = SimpleNamespace(title="Doc Title")
    # w.data would normally come from object_store.get_bytes(version.original_object_key)
    # inside ensure_loaded -- set directly since this test isn't exercising that path.
    workspace.data = b"%PDF-1.4\nplaceholder\n%%EOF\n"
    workspace.filename = "doc.pdf"
    return workspace


@pytest.mark.asyncio
async def test_reindex_without_clearing_cache_never_attaches_promoted_field() -> None:
    """Reproduces the bug: resuming at EXTRACT_DOCUMENT_INTELLIGENCE alone is not enough."""
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    document_id = new_id()
    version_id = new_id()

    provider = _FakeProvider({"vendor_name": "Acme Corp"})
    extraction_repo = InMemoryDocumentExtractionRepository()
    built = build_local_container(
        document_intelligence_provider=provider,  # type: ignore[arg-type]
        document_extraction_repo=extraction_repo,
    )
    service = built.require_process_ingestion()

    # Run 1: DI disabled, chunk for real -- persists the "chunks" artifact.
    run1_id = new_id()
    ws1 = await _seeded_workspace(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        ingestion_run_id=run1_id,
        options=None,
    )
    context1 = StageContext(
        tenant=tenant,
        ingestion_run_id=run1_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
    )
    outcome1 = await DocumentPipeline(ws1).stage_chunk(context1)
    assert outcome1.status.value == "completed"
    assert len(ws1.chunks) > 0
    for chunk in ws1.chunks:
        assert "document_intelligence" not in chunk.metadata

    # Run 2: fresh workspace, new run_id, DI enabled with a promoted field.
    # ensure_loaded will rehydrate w.chunks from run 1's stale "chunks"
    # artifact, and stage_chunk will short-circuit on it -- the bug.
    run2_id = new_id()
    options = DocumentIntelligenceIngestOptions(
        enabled=True,
        custom_fields=[
            ModelFieldSpec(
                name="vendor_name",
                label="Vendor name",
                field_type=FieldType.STRING,
                promote_to_document_metadata=True,
            ),
        ],
    )
    ws2 = _fresh_workspace(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        ingestion_run_id=run2_id,
        options=options,
    )
    context2 = StageContext(
        tenant=tenant,
        ingestion_run_id=run2_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
    )
    pipeline2 = DocumentPipeline(ws2)
    di_outcome = await pipeline2.stage_extract_document_intelligence(context2)
    assert di_outcome.status.value == "completed"
    chunk_outcome = await pipeline2.stage_chunk(context2)
    assert chunk_outcome.status.value == "completed"
    assert len(ws2.chunks) > 0
    for chunk in ws2.chunks:
        # Bug reproduced: stale cached chunks, no promoted metadata attached.
        assert "document_intelligence" not in chunk.metadata


@pytest.mark.asyncio
async def test_clearing_artifacts_before_reindex_actually_attaches_promoted_field() -> None:
    """Proves the fix: clearing chunks/embeddings/graph lets stage_chunk redo its work."""
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    document_id = new_id()
    version_id = new_id()

    provider = _FakeProvider({"vendor_name": "Acme Corp"})
    extraction_repo = InMemoryDocumentExtractionRepository()
    built = build_local_container(
        document_intelligence_provider=provider,  # type: ignore[arg-type]
        document_extraction_repo=extraction_repo,
    )
    service = built.require_process_ingestion()
    object_store = built.require_object_store()

    run1_id = new_id()
    ws1 = await _seeded_workspace(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        ingestion_run_id=run1_id,
        options=None,
    )
    context1 = StageContext(
        tenant=tenant,
        ingestion_run_id=run1_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
    )
    await DocumentPipeline(ws1).stage_chunk(context1)

    # Simulate ReindexDocumentService's DOCUMENT_INTELLIGENCE-scope clearing:
    # delete chunks/embeddings/graph, leave parse_raw/normalized alone.
    for name in ("chunks", "embeddings", "graph"):
        key = artifact_key(tenant.tenant_id, document_id, version_id, name)
        await object_store.delete_prefix(tenant, prefix=key)

    run2_id = new_id()
    options = DocumentIntelligenceIngestOptions(
        enabled=True,
        custom_fields=[
            ModelFieldSpec(
                name="vendor_name",
                label="Vendor name",
                field_type=FieldType.STRING,
                promote_to_document_metadata=True,
            ),
        ],
    )
    ws2 = _fresh_workspace(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        ingestion_run_id=run2_id,
        options=options,
    )
    context2 = StageContext(
        tenant=tenant,
        ingestion_run_id=run2_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
    )
    pipeline2 = DocumentPipeline(ws2)
    await pipeline2.stage_extract_document_intelligence(context2)
    chunk_outcome = await pipeline2.stage_chunk(context2)
    assert chunk_outcome.status.value == "completed"
    assert len(ws2.chunks) > 0
    for chunk in ws2.chunks:
        assert chunk.metadata.get("document_intelligence", {}).get("vendor_name") == "Acme Corp"

    # parse_raw/normalized were reused, not redone: ws2.raw/normalized came
    # from ensure_loaded's cache path, matching run 1's content verbatim.
    assert ws2.normalized is not None
    assert ws2.normalized.elements[0].normalized_content == "Some page content for chunking."
