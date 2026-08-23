"""Document Intelligence ingest-contract + no-op stage tests (Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graph_rag.api.app import create_app
from graph_rag.application.ingestion.stage_pipeline import DocumentPipeline, PipelineWorkspace
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.handlers import StageContext, StageOutcomeStatus
from graph_rag.domain.ingestion.stages import IngestionStageName
from graph_rag.domain.tenant import TenantContext


@pytest.mark.asyncio
async def test_document_intelligence_stage_handler_always_skips() -> None:
    workspace = PipelineWorkspace(service=None)  # type: ignore[arg-type]
    pipeline = DocumentPipeline(workspace)
    context = StageContext(
        tenant=TenantContext(tenant_id=new_id()),
        ingestion_run_id=new_id(),
        document_id=new_id(),
        version_id=new_id(),
        content_hash="hash",
        config_fingerprint="fp",
    )
    outcome = await pipeline.stage_skip_document_intelligence(context)
    assert outcome.status is StageOutcomeStatus.SKIPPED


def test_document_intelligence_stage_is_wired_into_pipeline_handlers() -> None:
    workspace = PipelineWorkspace(service=None)  # type: ignore[arg-type]
    pipeline = DocumentPipeline(workspace)
    handlers = pipeline.handlers()
    assert IngestionStageName.EXTRACT_DOCUMENT_INTELLIGENCE in handlers


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch):
    from graph_rag.config.settings import clear_settings_cache

    monkeypatch.setenv("AUTH_ENABLED", "false")
    clear_settings_cache()
    try:
        yield build_local_container()
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


def test_ingest_with_document_intelligence_options_is_accepted(
    client, tenant_headers, tmp_path: Path
) -> None:
    path = tmp_path / "sds.pdf"
    path.write_bytes(b"%PDF-1.4\nsds\n%%EOF\n")
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/documents/ingest",
            headers=tenant_headers,
            files={"file": ("sds.pdf", handle, "application/pdf")},
            data={
                "title": "SDS",
                "document_intelligence": '{"enabled": true, "model_id": "sds"}',
            },
        )
    assert response.status_code == 202, response.text
    run = client.get(
        f"/api/v1/ingestion-runs/{response.json()['ingestion_run_id']}",
        headers=tenant_headers,
    )
    assert run.status_code == 200
    stage_names = {stage["stage"] for stage in run.json()["stages"]}
    assert "EXTRACT_DOCUMENT_INTELLIGENCE" in stage_names


def test_ingest_with_invalid_document_intelligence_json_is_rejected(
    client, tenant_headers, tmp_path: Path
) -> None:
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.4\nbad\n%%EOF\n")
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/documents/ingest",
            headers=tenant_headers,
            files={"file": ("bad.pdf", handle, "application/pdf")},
            data={"title": "Bad", "document_intelligence": "{not json"},
        )
    assert response.status_code == 422, response.text


def test_ingest_with_unknown_document_intelligence_field_is_rejected(
    client, tenant_headers, tmp_path: Path
) -> None:
    path = tmp_path / "bad-schema.pdf"
    path.write_bytes(b"%PDF-1.4\nbad-schema\n%%EOF\n")
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/documents/ingest",
            headers=tenant_headers,
            files={"file": ("bad-schema.pdf", handle, "application/pdf")},
            data={"title": "Bad schema", "document_intelligence": '{"not_a_real_field": true}'},
        )
    assert response.status_code == 422, response.text


def test_ingest_without_document_intelligence_is_unaffected(
    client, tenant_headers, tmp_path: Path
) -> None:
    """Omitting the field is byte-for-byte the pre-Phase-3 upload path."""
    path = tmp_path / "plain.pdf"
    path.write_bytes(b"%PDF-1.4\nplain\n%%EOF\n")
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/documents/ingest",
            headers=tenant_headers,
            files={"file": ("plain.pdf", handle, "application/pdf")},
            data={"title": "Plain"},
        )
    assert response.status_code == 202, response.text
    run = client.get(
        f"/api/v1/ingestion-runs/{response.json()['ingestion_run_id']}",
        headers=tenant_headers,
    )
    assert run.status_code == 200
    assert len(run.json()["stages"]) == 23
