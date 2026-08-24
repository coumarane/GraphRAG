"""Configured field->entity Neo4j mapping through the real stage handlers (Phase 9).

Runs ``stage_extract_document_intelligence`` then ``stage_extract_graph`` in
sequence, mirroring ``test_document_intelligence_custom_model_stage.py``'s
direct-stage-construction pattern. Verifies the design doc's own test
requirement: "graph nodes only for mapped fields."
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceIngestOptions,
    ExtractedFieldResult,
    ExtractionMethod,
    confidence_band,
)
from graph_rag.application.ingestion import stage_pipeline as stage_pipeline_module
from graph_rag.application.ingestion.parsing_audit_collector import ParsingAuditCollector
from graph_rag.application.ingestion.stage_pipeline import DocumentPipeline, PipelineWorkspace
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.document_intelligence.records import (
    DocumentIntelligenceModelFieldRecord,
    DocumentIntelligenceModelRecord,
)
from graph_rag.domain.documents import NormalizedDocument, ParserInfo
from graph_rag.domain.graph.vocabulary import SEMANTIC_NODE_LABELS
from graph_rag.domain.ids import deterministic_id, new_id
from graph_rag.domain.ingestion.handlers import StageContext
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.parsing.types import RawParserResult
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.document_intelligence import (
    InMemoryDocumentExtractionRepository,
    InMemoryDocumentIntelligenceModelRepository,
)
from graph_rag.infrastructure.persistence.neo4j.memory import InMemoryGraphStore


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


async def _create_model(
    model_repo, tenant, *, model_key: str, field_entity_mappings: dict
) -> DocumentIntelligenceModelRecord:
    model_id = new_id()
    record = DocumentIntelligenceModelRecord(
        model_id=model_id,
        tenant_id=tenant.tenant_id,
        model_key=model_key,
        name=model_key.title(),
        field_entity_mappings=field_entity_mappings,
        fields=[
            DocumentIntelligenceModelFieldRecord(
                field_id=new_id(),
                model_id=model_id,
                tenant_id=tenant.tenant_id,
                name=name,
                label=name.title(),
                field_type="string",
            )
            for name in field_entity_mappings
        ],
    )
    return await model_repo.create_model(tenant, record)


@pytest.mark.asyncio
async def test_mapped_field_creates_entity_node_and_mentions_relationship() -> None:
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    model_repo = InMemoryDocumentIntelligenceModelRepository()
    await _create_model(
        model_repo,
        tenant,
        model_key="invoice",
        field_entity_mappings={"vendor_name": {"label": "Organization"}},
    )
    extraction_repo = InMemoryDocumentExtractionRepository()
    graph_store = InMemoryGraphStore()
    provider = _FakeProvider({"vendor_name": "Acme Corp"})
    built = build_local_container(
        document_intelligence_provider=provider,  # type: ignore[arg-type]
        document_extraction_repo=extraction_repo,
        document_intelligence_model_repo=model_repo,
        graph_store=graph_store,
    )
    service = built.require_process_ingestion()

    document_id = new_id()
    version_id = new_id()
    ingestion_run_id = new_id()
    options = DocumentIntelligenceIngestOptions(enabled=True, model_id="invoice")
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
    workspace.raw = RawParserResult(parser_name="test", page_count=1)
    workspace.normalized = NormalizedDocument(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        source_filename="doc.pdf",
        mime_type="application/pdf",
        page_count=1,
        parser_info=ParserInfo(parser_name="test", parser_version="1.0"),
    )
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
    await pipeline.stage_extract_graph(context)

    expected_node_id = deterministic_id(str(tenant.tenant_id), "Organization", "Acme Corp")
    assert expected_node_id in graph_store.nodes
    node = graph_store.nodes[expected_node_id]
    assert node.label == "Organization"
    assert node.properties["value"] == "Acme Corp"
    mentions = [
        rel
        for rel in graph_store.relationships.values()
        if rel.source_node_id == document_id and rel.target_node_id == expected_node_id
    ]
    assert len(mentions) == 1
    assert mentions[0].relationship_type == "MENTIONS"


@pytest.mark.asyncio
async def test_reingesting_same_value_merges_onto_same_node() -> None:
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    model_repo = InMemoryDocumentIntelligenceModelRepository()
    await _create_model(
        model_repo,
        tenant,
        model_key="invoice",
        field_entity_mappings={"vendor_name": {"label": "Organization"}},
    )
    extraction_repo = InMemoryDocumentExtractionRepository()
    graph_store = InMemoryGraphStore()
    provider = _FakeProvider({"vendor_name": "Acme Corp"})
    built = build_local_container(
        document_intelligence_provider=provider,  # type: ignore[arg-type]
        document_extraction_repo=extraction_repo,
        document_intelligence_model_repo=model_repo,
        graph_store=graph_store,
    )
    service = built.require_process_ingestion()

    async def _ingest_once(doc_id, ver_id):
        run_id = new_id()
        options = DocumentIntelligenceIngestOptions(enabled=True, model_id="invoice")
        run = IngestionRunRecord(
            ingestion_run_id=run_id,
            tenant_id=tenant.tenant_id,
            document_id=doc_id,
            version_id=ver_id,
            content_hash="hash",
            config_fingerprint="fp",
            metadata={"document_intelligence": options.model_dump(mode="json")},
        )
        workspace = PipelineWorkspace(service=service)
        workspace.tenant = tenant
        workspace.run = run
        workspace.version = SimpleNamespace(content_hash="hash")
        workspace.document = SimpleNamespace(title="Doc Title")
        workspace.audit = ParsingAuditCollector(
            tenant_id=tenant.tenant_id,
            document_id=doc_id,
            version_id=ver_id,
            ingestion_run_id=run_id,
        )
        workspace.data = b"%PDF-1.4\nplaceholder\n%%EOF\n"
        workspace.raw = RawParserResult(parser_name="test", page_count=1)
        workspace.normalized = NormalizedDocument(
            tenant_id=tenant.tenant_id,
            document_id=doc_id,
            version_id=ver_id,
            source_filename="doc.pdf",
            mime_type="application/pdf",
            page_count=1,
            parser_info=ParserInfo(parser_name="test", parser_version="1.0"),
        )
        context = StageContext(
            tenant=tenant,
            ingestion_run_id=run_id,
            document_id=doc_id,
            version_id=ver_id,
            content_hash="hash",
            config_fingerprint="fp",
        )
        pipeline = DocumentPipeline(workspace)
        await pipeline.stage_extract_document_intelligence(context)
        await pipeline.stage_extract_graph(context)

    await _ingest_once(new_id(), new_id())
    node_count_after_first = len(
        [n for n in graph_store.nodes.values() if n.label == "Organization"]
    )
    await _ingest_once(new_id(), new_id())
    node_count_after_second = len(
        [n for n in graph_store.nodes.values() if n.label == "Organization"]
    )
    assert node_count_after_first == 1
    assert node_count_after_second == 1


@pytest.mark.asyncio
async def test_model_with_no_mappings_creates_zero_semantic_nodes() -> None:
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    model_repo = InMemoryDocumentIntelligenceModelRepository()
    model_id = new_id()
    await model_repo.create_model(
        tenant,
        DocumentIntelligenceModelRecord(
            model_id=model_id,
            tenant_id=tenant.tenant_id,
            model_key="plain",
            name="Plain",
            fields=[
                DocumentIntelligenceModelFieldRecord(
                    field_id=new_id(),
                    model_id=model_id,
                    tenant_id=tenant.tenant_id,
                    name="notes",
                    label="Notes",
                    field_type="string",
                ),
            ],
        ),
    )
    extraction_repo = InMemoryDocumentExtractionRepository()
    graph_store = InMemoryGraphStore()
    provider = _FakeProvider({"notes": "some notes"})
    built = build_local_container(
        document_intelligence_provider=provider,  # type: ignore[arg-type]
        document_extraction_repo=extraction_repo,
        document_intelligence_model_repo=model_repo,
        graph_store=graph_store,
    )
    service = built.require_process_ingestion()

    document_id = new_id()
    version_id = new_id()
    ingestion_run_id = new_id()
    options = DocumentIntelligenceIngestOptions(enabled=True, model_id="plain")
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
    workspace.raw = RawParserResult(parser_name="test", page_count=1)
    workspace.normalized = NormalizedDocument(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        source_filename="doc.pdf",
        mime_type="application/pdf",
        page_count=1,
        parser_info=ParserInfo(parser_name="test", parser_version="1.0"),
    )
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
    await pipeline.stage_extract_graph(context)

    semantic_nodes = [n for n in graph_store.nodes.values() if n.label in SEMANTIC_NODE_LABELS]
    assert semantic_nodes == []


@pytest.mark.asyncio
async def test_unresolved_mapped_field_produces_no_node_and_does_not_crash() -> None:
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    model_repo = InMemoryDocumentIntelligenceModelRepository()
    await _create_model(
        model_repo,
        tenant,
        model_key="invoice",
        field_entity_mappings={"vendor_name": {"label": "Organization"}},
    )
    extraction_repo = InMemoryDocumentExtractionRepository()
    graph_store = InMemoryGraphStore()
    provider = _FakeProvider({})  # extraction resolves nothing
    built = build_local_container(
        document_intelligence_provider=provider,  # type: ignore[arg-type]
        document_extraction_repo=extraction_repo,
        document_intelligence_model_repo=model_repo,
        graph_store=graph_store,
    )
    service = built.require_process_ingestion()

    document_id = new_id()
    version_id = new_id()
    ingestion_run_id = new_id()
    options = DocumentIntelligenceIngestOptions(enabled=True, model_id="invoice")
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
    workspace.raw = RawParserResult(parser_name="test", page_count=1)
    workspace.normalized = NormalizedDocument(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        source_filename="doc.pdf",
        mime_type="application/pdf",
        page_count=1,
        parser_info=ParserInfo(parser_name="test", parser_version="1.0"),
    )
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
    await pipeline.stage_extract_graph(context)

    semantic_nodes = [n for n in graph_store.nodes.values() if n.label in SEMANTIC_NODE_LABELS]
    assert semantic_nodes == []
