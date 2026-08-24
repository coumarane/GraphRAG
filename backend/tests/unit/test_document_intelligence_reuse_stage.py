"""Cost-control reuse through the real stage handler (Phase 6).

Constructed directly against ``DocumentPipeline.stage_extract_document_intelligence``
rather than the public upload endpoint: document-level dedup blocks
re-uploading identical bytes against the same version, and ``/reprocess``
does not invoke this stage today (it never resumes earlier than ``CHUNK``,
which sits after ``EXTRACT_DOCUMENT_INTELLIGENCE``). Two ``IngestionRunRecord``s
are built in-hand, sharing one document/version identity, and run through the
stage directly against a shared in-memory repository.
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
from graph_rag.application.ingestion.stage_pipeline import DocumentPipeline, PipelineWorkspace
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.documents import NormalizedDocument, ParserInfo
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.handlers import StageContext, StageOutcomeStatus
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.parsing.types import RawParserResult
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.document_intelligence import (
    InMemoryDocumentExtractionRepository,
)


class _CountingProvider:
    """Duck-typed provider: records each extract() call's requested field names."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def extract(self, request):
        names = [field.name for field in request.fields]
        self.calls.append(names)
        fields = [
            ExtractedFieldResult(
                name=name,
                value=f"value-{name}",
                confidence=0.8,
                confidence_band=confidence_band(0.8),
                extraction_method=ExtractionMethod.RULES,
            )
            for name in names
        ]
        return stage_pipeline_module.DocumentIntelligenceExtractionResult(
            fields=fields,
            requested_field_names=names,
            unresolved_field_names=[],
        )


def _fields(*names: str) -> list[ModelFieldSpec]:
    return [
        ModelFieldSpec(name=name, label=name.title(), field_type=FieldType.STRING) for name in names
    ]


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch):
    from graph_rag.config.settings import clear_settings_cache

    monkeypatch.setenv("AUTH_ENABLED", "false")
    clear_settings_cache()
    try:
        provider = _CountingProvider()
        repo = InMemoryDocumentExtractionRepository()
        built = build_local_container(
            document_intelligence_provider=provider,  # type: ignore[arg-type]
            document_extraction_repo=repo,
        )
        yield built, provider, repo
    finally:
        clear_settings_cache()


async def _run_stage(
    service,
    *,
    tenant: TenantContext,
    document_id,
    version_id,
    content_hash: str,
    field_names: list[str],
):
    ingestion_run_id = new_id()
    run = IngestionRunRecord(
        ingestion_run_id=ingestion_run_id,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        content_hash=content_hash,
        config_fingerprint="fp",
        metadata={
            "document_intelligence": DocumentIntelligenceIngestOptions(
                enabled=True, custom_fields=_fields(*field_names)
            ).model_dump(mode="json")
        },
    )
    workspace = PipelineWorkspace(service=service)
    workspace.tenant = tenant
    workspace.run = run
    workspace.version = SimpleNamespace(content_hash=content_hash)
    workspace.document = SimpleNamespace()
    workspace.audit = SimpleNamespace()
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
        content_hash=content_hash,
        config_fingerprint="fp",
    )
    pipeline = DocumentPipeline(workspace)
    outcome = await pipeline.stage_extract_document_intelligence(context)
    return outcome, run


@pytest.mark.asyncio
async def test_unchanged_fields_make_zero_provider_calls_on_repeat(container) -> None:
    built, provider, repo = container
    service = built.require_process_ingestion()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    document_id = new_id()
    version_id = new_id()

    outcome1, _run1 = await _run_stage(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        field_names=["a", "b"],
    )
    assert outcome1.status is StageOutcomeStatus.COMPLETED
    assert provider.calls == [["a", "b"]]

    outcome2, _run2 = await _run_stage(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        field_names=["a", "b"],
    )
    assert provider.calls == [["a", "b"]]  # unchanged -- no second call at all
    assert outcome2.status is StageOutcomeStatus.COMPLETED
    assert outcome2.warning is not None
    assert "reused 2/2" in outcome2.warning

    runs = await repo.list_runs_for_version(tenant, document_id, version_id)
    assert len(runs) == 2
    assert runs[0].fingerprint == runs[1].fingerprint


@pytest.mark.asyncio
async def test_adding_one_field_only_extracts_that_field(container) -> None:
    built, provider, repo = container
    service = built.require_process_ingestion()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    document_id = new_id()
    version_id = new_id()

    await _run_stage(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        field_names=["a", "b"],
    )
    outcome2, _run2 = await _run_stage(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        field_names=["a", "b", "c"],
    )
    assert provider.calls == [["a", "b"], ["c"]]
    assert outcome2.status is StageOutcomeStatus.COMPLETED

    runs = await repo.list_runs_for_version(tenant, document_id, version_id)
    newest_run = runs[0]
    fields = await repo.list_fields_for_run(tenant, newest_run.run_id)
    assert {field.name for field in fields} == {"a", "b", "c"}
    assert runs[0].fingerprint != runs[1].fingerprint


@pytest.mark.asyncio
async def test_provider_version_bump_invalidates_reuse(
    container, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, provider, _repo = container
    service = built.require_process_ingestion()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    document_id = new_id()
    version_id = new_id()

    await _run_stage(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        field_names=["a", "b"],
    )
    monkeypatch.setattr(stage_pipeline_module, "INTERNAL_PROVIDER_VERSION", "9.9.9-test")
    await _run_stage(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        field_names=["a", "b"],
    )
    assert provider.calls == [["a", "b"], ["a", "b"]]
