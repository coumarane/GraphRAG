"""API and CLI Phase 12 tests."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from enterprise_rag.api.app import create_app
from enterprise_rag.application.runtime import ElementView, build_local_container
from enterprise_rag.cli.main import app as cli_app
from enterprise_rag.cli.main import set_container
from enterprise_rag.domain.ids import deterministic_id, new_id
from enterprise_rag.domain.modality import Modality


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch):
    from enterprise_rag.config.settings import clear_settings_cache

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
    tenant_key = "demo"
    return {
        "X-Tenant-Key": tenant_key,
        "X-Correlation-ID": str(new_id()),
    }


def test_health_live_and_ready(client) -> None:
    live = client.get("/api/v1/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


def test_ingest_upload_and_get_document(client, container, tenant_headers, tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-1.4\nsample\n%%EOF\n")
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/documents/ingest",
            headers=tenant_headers,
            files={"file": ("sample.pdf", handle, "application/pdf")},
            data={"title": "Sample", "parser_requested": "auto"},
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert "ingestion_run_id" in body
    document_id = body["document_id"]

    got = client.get(f"/api/v1/documents/{document_id}", headers=tenant_headers)
    assert got.status_code == 200
    assert got.json()["title"].lower() == "sample"

    listed = client.get("/api/v1/documents", headers=tenant_headers)
    assert listed.status_code == 200
    listed_body = listed.json()
    assert listed_body["total"] >= 1
    assert any(item["document_id"] == document_id for item in listed_body["items"])

    chunks = client.get(f"/api/v1/documents/{document_id}/chunks", headers=tenant_headers)
    assert chunks.status_code == 200
    assert "items" in chunks.json()

    reprocess = client.post(
        f"/api/v1/documents/{document_id}/reprocess?scope=full",
        headers=tenant_headers,
    )
    assert reprocess.status_code == 202, reprocess.text
    assert reprocess.json()["document_id"] == document_id
    assert reprocess.json()["ingestion_run_id"]

    run = client.get(
        f"/api/v1/ingestion-runs/{body['ingestion_run_id']}",
        headers=tenant_headers,
    )
    assert run.status_code == 200
    assert run.json()["status"] == "pending"
    assert len(run.json()["stages"]) == 22


def test_query_and_retrieval_endpoints(client, tenant_headers) -> None:
    search = client.post(
        "/api/v1/retrieval/search",
        headers=tenant_headers,
        json={"question": "storage temperature", "mode": "naive", "rerank": False},
    )
    assert search.status_code == 200
    assert "retrieval_trace_id" in search.json()

    query = client.post(
        "/api/v1/query",
        headers=tenant_headers,
        json={"question": "storage temperature", "mode": "naive", "rerank": False},
    )
    assert query.status_code == 200
    body = query.json()
    assert "answer" in body
    assert "retrieval_mode" in body
    assert "citations" in body


def test_graph_search_and_delete(client, container, tenant_headers, tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.4\nx\n%%EOF\n")
    with path.open("rb") as handle:
        ingest = client.post(
            "/api/v1/documents/ingest",
            headers=tenant_headers,
            files={"file": ("doc.pdf", handle, "application/pdf")},
        )
    document_id = ingest.json()["document_id"]
    version_id = ingest.json()["version_id"]
    tenant_id = deterministic_id("tenant", "demo")
    doc_uuid = UUID(document_id)
    container.elements[(tenant_id, doc_uuid)] = [
        ElementView(
            element_id=new_id(),
            document_id=doc_uuid,
            version_id=UUID(version_id),
            element_type="text",
            modality=Modality.TEXT,
            page_start=1,
            page_end=1,
            preview="hello",
        )
    ]
    elements = client.get(
        f"/api/v1/documents/{document_id}/elements",
        headers=tenant_headers,
    )
    assert elements.status_code == 200
    assert elements.json()["total"] == 1

    graph = client.post(
        "/api/v1/graph/search",
        headers=tenant_headers,
        json={"names": ["silicone"], "depth": 1, "limit": 5},
    )
    assert graph.status_code == 200

    deleted = client.delete(f"/api/v1/documents/{document_id}", headers=tenant_headers)
    assert deleted.status_code == 202
    assert "operation_id" in deleted.json()


def test_missing_tenant_returns_problem_details(client) -> None:
    response = client.get("/api/v1/documents/" + str(new_id()))
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert "correlation_id" in body


def test_cli_ingest_and_query(tmp_path: Path) -> None:
    container = build_local_container()
    set_container(container)
    runner = CliRunner()
    path = tmp_path / "cli.pdf"
    sample = Path("examples/sample.pdf")
    if sample.exists():
        path.write_bytes(sample.read_bytes())
    else:
        path.write_bytes(b"%PDF-1.4\ncli\n%%EOF\n")
    ingest = runner.invoke(
        cli_app,
        ["ingest", str(path), "--tenant-id", "demo", "--wait", "--output", "json"],
    )
    assert ingest.exit_code == 0, ingest.output
    payload = json.loads(_extract_json(ingest.output))
    assert payload["ingestion_run_id"]
    assert payload["status"] in {"completed", "completed_with_warnings", "accepted"}

    query = runner.invoke(
        cli_app,
        [
            "query",
            "Summarize the document",
            "--tenant-id",
            "demo",
            "--mode",
            "auto",
            "--output",
            "json",
        ],
    )
    assert query.exit_code == 0, query.output
    answer = json.loads(_extract_json(query.output))
    assert "answer" in answer
    assert "retrieval_mode" in answer


def test_cli_reindex_and_delete(tmp_path: Path) -> None:
    container = build_local_container()
    set_container(container)
    runner = CliRunner()
    path = tmp_path / "ops.pdf"
    path.write_bytes(b"%PDF-1.4\nops\n%%EOF\n")
    ingest = runner.invoke(
        cli_app,
        ["ingest", str(path), "--tenant-id", "demo", "--output", "json"],
    )
    assert ingest.exit_code == 0, ingest.output
    document_id = json.loads(_extract_json(ingest.output))["document_id"]

    rebuild = runner.invoke(
        cli_app,
        ["rebuild-vectors", document_id, "--tenant-id", "demo", "--output", "json"],
    )
    assert rebuild.exit_code == 0, rebuild.output
    rebuild_body = json.loads(_extract_json(rebuild.output))
    assert rebuild_body["scope"] == "vectors"
    assert rebuild_body["ingestion_run_id"]

    deleted = runner.invoke(
        cli_app,
        ["delete-document", document_id, "--tenant-id", "demo", "--output", "json"],
    )
    assert deleted.exit_code == 0, deleted.output
    delete_body = json.loads(_extract_json(deleted.output))
    assert delete_body["status"] in {"completed", "partial"}


def _extract_json(text: str) -> str:
    start = text.find("{")
    assert start >= 0, text
    return text[start:]
