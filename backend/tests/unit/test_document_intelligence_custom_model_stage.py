"""Persisted custom-model resolution through the real stage handler (Phase 7).

Constructed directly against ``DocumentPipeline.stage_extract_document_intelligence``
rather than the public upload endpoint -- see
``test_document_intelligence_reuse_stage.py``'s module docstring for why (document-
level dedup and ``/reprocess`` don't exercise this stage today).
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
from graph_rag.domain.document_intelligence.records import (
    DocumentIntelligenceModelFieldRecord,
    DocumentIntelligenceModelRecord,
)
from graph_rag.domain.documents import NormalizedDocument, ParserInfo
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.handlers import StageContext, StageOutcomeStatus
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.parsing.types import RawParserResult
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.document_intelligence import (
    InMemoryDocumentExtractionRepository,
    InMemoryDocumentIntelligenceModelRepository,
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


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch):
    from graph_rag.config.settings import clear_settings_cache

    monkeypatch.setenv("AUTH_ENABLED", "false")
    clear_settings_cache()
    try:
        provider = _CountingProvider()
        extraction_repo = InMemoryDocumentExtractionRepository()
        model_repo = InMemoryDocumentIntelligenceModelRepository()
        built = build_local_container(
            document_intelligence_provider=provider,  # type: ignore[arg-type]
            document_extraction_repo=extraction_repo,
            document_intelligence_model_repo=model_repo,
        )
        yield built, provider, extraction_repo, model_repo
    finally:
        clear_settings_cache()


async def _create_custom_model(
    model_repo, tenant: TenantContext, *, model_key: str, field_names: list[str]
) -> DocumentIntelligenceModelRecord:
    model_id = new_id()
    record = DocumentIntelligenceModelRecord(
        model_id=model_id,
        tenant_id=tenant.tenant_id,
        model_key=model_key,
        name=model_key.title(),
        fields=[
            DocumentIntelligenceModelFieldRecord(
                field_id=new_id(),
                model_id=model_id,
                tenant_id=tenant.tenant_id,
                name=name,
                label=name.title(),
                field_type="string",
                sort_order=index,
            )
            for index, name in enumerate(field_names)
        ],
    )
    return await model_repo.create_model(tenant, record)


async def _run_stage(
    service,
    *,
    tenant: TenantContext,
    document_id,
    version_id,
    content_hash: str,
    options: DocumentIntelligenceIngestOptions,
):
    ingestion_run_id = new_id()
    run = IngestionRunRecord(
        ingestion_run_id=ingestion_run_id,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        content_hash=content_hash,
        config_fingerprint="fp",
        metadata={"document_intelligence": options.model_dump(mode="json")},
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
async def test_custom_model_round_trip_resolves_persisted_fields(container) -> None:
    built, provider, _extraction_repo, model_repo = container
    service = built.require_process_ingestion()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    await _create_custom_model(
        model_repo, tenant, model_key="invoice", field_names=["invoice_number", "total_amount"]
    )

    outcome, _run = await _run_stage(
        service,
        tenant=tenant,
        document_id=new_id(),
        version_id=new_id(),
        content_hash="hash-v1",
        options=DocumentIntelligenceIngestOptions(enabled=True, model_id="invoice"),
    )

    assert outcome.status is StageOutcomeStatus.COMPLETED
    assert provider.calls == [["invoice_number", "total_amount"]]


@pytest.mark.asyncio
async def test_custom_model_resolved_by_uuid_model_id(container) -> None:
    built, provider, _extraction_repo, model_repo = container
    service = built.require_process_ingestion()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    record = await _create_custom_model(
        model_repo, tenant, model_key="invoice-v2", field_names=["invoice_number"]
    )

    outcome, _run = await _run_stage(
        service,
        tenant=tenant,
        document_id=new_id(),
        version_id=new_id(),
        content_hash="hash-v1",
        options=DocumentIntelligenceIngestOptions(enabled=True, model_id=str(record.model_id)),
    )

    assert outcome.status is StageOutcomeStatus.COMPLETED
    assert provider.calls == [["invoice_number"]]


@pytest.mark.asyncio
async def test_custom_model_reuse_across_runs_matches_on_model_key(container) -> None:
    """Confirms Phase 6 reuse.py's model_key matching still works for custom models."""
    built, provider, _extraction_repo, model_repo = container
    service = built.require_process_ingestion()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    await _create_custom_model(
        model_repo, tenant, model_key="invoice", field_names=["invoice_number"]
    )
    document_id, version_id = new_id(), new_id()

    await _run_stage(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        options=DocumentIntelligenceIngestOptions(enabled=True, model_id="invoice"),
    )
    outcome2, _run2 = await _run_stage(
        service,
        tenant=tenant,
        document_id=document_id,
        version_id=version_id,
        content_hash="hash-v1",
        options=DocumentIntelligenceIngestOptions(enabled=True, model_id="invoice"),
    )

    assert provider.calls == [["invoice_number"]]  # second run reused, zero new provider calls
    assert outcome2.status is StageOutcomeStatus.COMPLETED
    assert "reused 1/1" in (outcome2.warning or "")


@pytest.mark.asyncio
async def test_other_tenants_custom_model_id_does_not_resolve(container) -> None:
    """Cross-tenant isolation proven through the real stage + real repo, not just the
    pure resolution function -- a UUID model_id (or model_key slug) belonging to tenant
    A must not resolve any fields when tenant B's ingestion run references it."""
    built, provider, _extraction_repo, model_repo = container
    service = built.require_process_ingestion()
    tenant_a = TenantContext(tenant_id=new_id(), tenant_key="tenant-a")
    tenant_b = TenantContext(tenant_id=new_id(), tenant_key="tenant-b")
    record = await _create_custom_model(
        model_repo, tenant_a, model_key="invoice", field_names=["invoice_number"]
    )

    outcome, _run = await _run_stage(
        service,
        tenant=tenant_b,
        document_id=new_id(),
        version_id=new_id(),
        content_hash="hash-v1",
        options=DocumentIntelligenceIngestOptions(enabled=True, model_id="invoice"),
    )
    assert outcome.status is StageOutcomeStatus.COMPLETED_WITH_WARNINGS
    assert provider.calls == []  # never called -- nothing resolved

    outcome_by_uuid, _run2 = await _run_stage(
        service,
        tenant=tenant_b,
        document_id=new_id(),
        version_id=new_id(),
        content_hash="hash-v1",
        options=DocumentIntelligenceIngestOptions(enabled=True, model_id=str(record.model_id)),
    )
    assert outcome_by_uuid.status is StageOutcomeStatus.COMPLETED_WITH_WARNINGS
    assert provider.calls == []


@pytest.mark.asyncio
async def test_ad_hoc_custom_fields_with_no_model_id_still_works_with_model_repo_present(
    container,
) -> None:
    """Regression guard: threading document_intelligence_model_repo through must not
    change ad-hoc (no model_id) behavior at all."""
    built, provider, _extraction_repo, _model_repo = container
    service = built.require_process_ingestion()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")

    outcome, _run = await _run_stage(
        service,
        tenant=tenant,
        document_id=new_id(),
        version_id=new_id(),
        content_hash="hash-v1",
        options=DocumentIntelligenceIngestOptions(
            enabled=True,
            custom_fields=[
                ModelFieldSpec(name="batch_id", label="Batch ID", field_type=FieldType.STRING)
            ],
        ),
    )
    assert outcome.status is StageOutcomeStatus.COMPLETED
    assert provider.calls == [["batch_id"]]
