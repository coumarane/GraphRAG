"""A semantic graph failure is a stage warning, and the structural graph remains."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from graph_rag.application.ingestion import stage_pipeline as stage_pipeline_module
from graph_rag.application.ingestion.parsing_audit_collector import ParsingAuditCollector
from graph_rag.application.ingestion.stage_pipeline import DocumentPipeline, PipelineWorkspace
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.documents import NormalizedDocument, ParserInfo
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.handlers import StageContext, StageOutcomeStatus
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.parsing.types import RawParserResult
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.neo4j.memory import InMemoryGraphStore


class _FailingGraphBuilder:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def build(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("semantic down")


@pytest.mark.asyncio
async def test_semantic_graph_failure_completes_the_stage_with_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stage_pipeline_module,
        "BuildKnowledgeGraphService",
        _FailingGraphBuilder,
    )
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    graph_store = InMemoryGraphStore()
    built = build_local_container(graph_store=graph_store)
    service = built.require_process_ingestion()
    service.structured_extractor = object()
    service.semantic_graph = True
    document_id = new_id()
    version_id = new_id()
    ingestion_run_id = new_id()
    run = IngestionRunRecord(
        ingestion_run_id=ingestion_run_id,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        config_fingerprint="fp",
    )
    workspace = PipelineWorkspace(service=service)
    workspace.tenant = tenant
    workspace.run = run
    workspace.version = SimpleNamespace(content_hash="hash-v1")
    workspace.document = SimpleNamespace(title="Serum")
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
        source_filename="serum.pdf",
        mime_type="application/pdf",
        page_count=1,
        parser_info=ParserInfo(parser_name="test", parser_version="1.0"),
    )
    outcome = await DocumentPipeline(workspace).stage_extract_graph(
        StageContext(
            tenant=tenant,
            ingestion_run_id=ingestion_run_id,
            document_id=document_id,
            version_id=version_id,
            content_hash="hash-v1",
            config_fingerprint="fp",
        )
    )
    assert outcome.status is StageOutcomeStatus.COMPLETED_WITH_WARNINGS
    assert outcome.warning == "semantic_graph_failed:RuntimeError"
    assert workspace.raw.warnings == ["semantic_graph_failed:RuntimeError"]
    assert graph_store.nodes
