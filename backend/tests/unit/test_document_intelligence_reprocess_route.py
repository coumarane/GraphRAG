"""``POST /documents/{id}/reprocess?scope=document_intelligence`` route tests.

Lets a user run Document Intelligence extraction on an already-processed
document without re-uploading the file -- see
``application/deletion/reindex.py``'s ``DOCUMENT_INTELLIGENCE`` scope and
``test_document_intelligence_reindex_cache_clearing.py`` for the underlying
mechanism this route exercises end-to-end.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from graph_rag.api.app import create_app
from graph_rag.application.document_intelligence.models import (
    ExtractedFieldResult,
    ExtractionMethod,
    confidence_band,
)
from graph_rag.application.ingestion import stage_pipeline as stage_pipeline_module
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.ids import new_id
from graph_rag.infrastructure.persistence.memory.document_intelligence import (
    InMemoryDocumentExtractionRepository,
)


class _FakeProvider:
    async def extract(self, request):
        names = [field.name for field in request.fields]
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
            fields=fields, requested_field_names=names, unresolved_field_names=[]
        )


@pytest.fixture
def extraction_repo():
    return InMemoryDocumentExtractionRepository()


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch, extraction_repo):
    from graph_rag.config.settings import clear_settings_cache

    monkeypatch.setenv("AUTH_ENABLED", "false")
    clear_settings_cache()
    try:
        yield build_local_container(
            auto_process_ingest=True,
            document_intelligence_provider=_FakeProvider(),  # type: ignore[arg-type]
            document_extraction_repo=extraction_repo,
        )
    finally:
        clear_settings_cache()


@pytest.fixture
def client(container):
    return TestClient(create_app(container))


@pytest.fixture
def tenant_headers():
    return {
        "X-Tenant-Key": "demo",
        "X-Correlation-ID": str(new_id()),
    }


def _ingest_ready_document(client, tenant_headers, tmp_path: Path) -> str:
    sample = Path("../data/examples/sample.pdf")
    if not sample.exists():
        pytest.skip("../data/examples/sample.pdf missing")
    dest = tmp_path / "sample.pdf"
    dest.write_bytes(sample.read_bytes())
    with dest.open("rb") as handle:
        response = client.post(
            "/api/v1/documents/ingest",
            headers=tenant_headers,
            files={"file": ("sample.pdf", handle, "application/pdf")},
            data={"title": "Sample"},
        )
    assert response.status_code == 202, response.text
    return response.json()["document_id"]


def test_reprocess_document_intelligence_scope_requires_body(
    client, tenant_headers, tmp_path: Path
) -> None:
    document_id = _ingest_ready_document(client, tenant_headers, tmp_path)
    response = client.post(
        f"/api/v1/documents/{document_id}/reprocess?scope=document_intelligence",
        headers=tenant_headers,
    )
    assert response.status_code == 422, response.text


def test_reprocess_document_intelligence_scope_rejects_disabled_options(
    client, tenant_headers, tmp_path: Path
) -> None:
    document_id = _ingest_ready_document(client, tenant_headers, tmp_path)
    response = client.post(
        f"/api/v1/documents/{document_id}/reprocess?scope=document_intelligence",
        headers=tenant_headers,
        json={"document_intelligence": {"enabled": False}},
    )
    assert response.status_code == 422, response.text


def test_reprocess_document_intelligence_scope_runs_and_persists_extraction(
    client, tenant_headers, tmp_path: Path, container, extraction_repo
) -> None:
    document_id = _ingest_ready_document(client, tenant_headers, tmp_path)

    response = client.post(
        f"/api/v1/documents/{document_id}/reprocess?scope=document_intelligence",
        headers=tenant_headers,
        json={"document_intelligence": {"enabled": True, "model_id": "layout"}},
    )
    assert response.status_code == 202, response.text
    ingestion_run_id = UUID(response.json()["ingestion_run_id"])
    assert ingestion_run_id is not None

    # auto_process_ingest=True runs the background task synchronously within
    # TestClient's request lifecycle -- the auto-enqueue gate extension is
    # what makes this actually execute rather than sitting PENDING forever
    # (confirmed today's GRAPH scope silently never runs without it).
    async def _check() -> None:
        tenant = await container.resolve_tenant(tenant_key="demo")
        run = await container.require_ingestion_repo().get_run(tenant, ingestion_run_id)
        assert run is not None
        runs = await extraction_repo.list_runs_for_version(tenant, run.document_id, run.version_id)
        assert len(runs) >= 1

    asyncio.run(_check())
