"""``GET /api/v1/documents/{id}/extractions`` route tests (Phase 8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graph_rag.api.app import create_app
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.document_intelligence.records import (
    DocumentExtractedFieldRecord,
    DocumentExtractionRunRecord,
)
from graph_rag.domain.ids import new_id


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


def _ingest_document(client, tenant_headers, tmp_path: Path, name: str = "doc.pdf") -> dict:
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4\nplaceholder\n%%EOF\n")
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/documents/ingest",
            headers=tenant_headers,
            files={"file": (name, handle, "application/pdf")},
            data={"title": "Doc"},
        )
    assert response.status_code == 202, response.text
    return response.json()


async def _seed_run(
    container,
    *,
    tenant_key: str,
    document_id,
    version_id,
    status: str = "completed",
    fields: list[tuple[str, float, str]] | None = None,
) -> DocumentExtractionRunRecord:
    tenant = await container.resolve_tenant(tenant_key=tenant_key)
    repo = container.require_document_extraction_repo()
    run = await repo.create_run(
        tenant,
        DocumentExtractionRunRecord(
            run_id=new_id(),
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            model_key="sds",
            provider="internal",
            plugin_version="0.5.0",
            status=status,
            selected_fields=[name for name, _, _ in fields or []],
        ),
    )
    if fields:
        await repo.add_extracted_fields(
            tenant,
            run.run_id,
            [
                DocumentExtractedFieldRecord(
                    extracted_field_id=new_id(),
                    tenant_id=tenant.tenant_id,
                    run_id=run.run_id,
                    name=name,
                    value=f"value-{name}",
                    confidence=confidence,
                    confidence_band=band,
                    extraction_method="RULES",
                )
                for name, confidence, band in fields
            ],
        )
    return run


def test_returns_seeded_run_with_low_confidence_field_not_dropped(
    client, container, tenant_headers, tmp_path: Path
) -> None:
    ingested = _ingest_document(client, tenant_headers, tmp_path)
    document_id = ingested["document_id"]
    version_id = ingested["version_id"]
    run = _run_async(
        _seed_run(
            container,
            tenant_key="demo",
            document_id=document_id,
            version_id=version_id,
            fields=[("product_name", 0.9, "HIGH"), ("lot_number", 0.2, "LOW")],
        )
    )

    response = client.get(f"/api/v1/documents/{document_id}/extractions", headers=tenant_headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["run_id"] == str(run.run_id)
    field_names = {field["name"] for field in items[0]["fields"]}
    assert field_names == {"product_name", "lot_number"}
    low = next(field for field in items[0]["fields"] if field["name"] == "lot_number")
    assert low["confidence_band"] == "LOW"


def test_no_version_id_falls_back_to_current_version(
    client, container, tenant_headers, tmp_path: Path
) -> None:
    ingested = _ingest_document(client, tenant_headers, tmp_path)
    document_id = ingested["document_id"]
    version_id = ingested["version_id"]
    _run_async(
        _seed_run(
            container,
            tenant_key="demo",
            document_id=document_id,
            version_id=version_id,
            fields=[("product_name", 0.9, "HIGH")],
        )
    )

    response = client.get(f"/api/v1/documents/{document_id}/extractions", headers=tenant_headers)
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1


def test_unknown_document_id_returns_404(client, tenant_headers) -> None:
    response = client.get(f"/api/v1/documents/{new_id()}/extractions", headers=tenant_headers)
    assert response.status_code == 404, response.text


def test_document_with_zero_runs_returns_empty_list_not_404(
    client, tenant_headers, tmp_path: Path
) -> None:
    ingested = _ingest_document(client, tenant_headers, tmp_path)
    response = client.get(
        f"/api/v1/documents/{ingested['document_id']}/extractions", headers=tenant_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_tenant_isolation_run_from_other_tenant_not_visible(
    client, container, tenant_headers, tmp_path: Path
) -> None:
    ingested = _ingest_document(client, tenant_headers, tmp_path)
    document_id = ingested["document_id"]
    version_id = ingested["version_id"]
    _run_async(
        _seed_run(
            container,
            tenant_key="demo",
            document_id=document_id,
            version_id=version_id,
            fields=[("product_name", 0.9, "HIGH")],
        )
    )

    other_tenant_headers = {"X-Tenant-Key": "other", "X-Correlation-ID": str(new_id())}
    response = client.get(
        f"/api/v1/documents/{document_id}/extractions", headers=other_tenant_headers
    )
    # A document registered under "demo" is not visible to "other" at all.
    assert response.status_code == 404, response.text


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)
