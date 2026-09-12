"""``POST /api/v1/documents/search`` route tests."""

from __future__ import annotations

import asyncio
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


def _run_async(coro):
    return asyncio.run(coro)


def _ingest_document(
    client,
    tenant_headers,
    tmp_path: Path,
    *,
    name: str | None = None,
    title: str = "Doc",
    document_type: str | None = None,
    tags: str | None = None,
) -> dict:
    # Document titles are always derived from the uploaded filename's stem
    # (register_source.py:_title_from_source deliberately ignores the form
    # "title" field so a stale form value can't mislabel a different file)
    # -- so encode the desired title into the filename itself.
    filename = name or f"{title.replace(' ', '_')}.pdf"
    path = tmp_path / filename
    # Content hash dedupes identical bytes across calls in the same test --
    # vary the payload per document so each upload is a distinct version.
    path.write_bytes(f"%PDF-1.4\n{title}::{filename}\n%%EOF\n".encode())
    data = {"document_intelligence": "{}"}
    if document_type:
        data["document_type"] = document_type
    if tags:
        data["tags"] = tags
    with path.open("rb") as handle:
        response = client.post(
            "/api/v1/documents/ingest",
            headers=tenant_headers,
            files={"file": (filename, handle, "application/pdf")},
            data=data,
        )
    assert response.status_code == 202, response.text
    return response.json()


async def _seed_run(
    container,
    *,
    tenant_key: str,
    document_id,
    version_id,
    fields: list[tuple[str, object]],
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
            model_key="certificate_of_analysis",
            provider="internal",
            status="completed",
            selected_fields=[name for name, _ in fields],
        ),
    )
    await repo.add_extracted_fields(
        tenant,
        run.run_id,
        [
            DocumentExtractedFieldRecord(
                extracted_field_id=new_id(),
                tenant_id=tenant.tenant_id,
                run_id=run.run_id,
                name=name,
                value=value,
                normalized_value=value,
                confidence=0.9,
                confidence_band="HIGH",
                extraction_method="RULES",
            )
            for name, value in fields
        ],
    )
    return run


def test_search_matches_title_text(client, tenant_headers, tmp_path: Path) -> None:
    _ingest_document(client, tenant_headers, tmp_path, title="Alpha Widget Spec")
    _ingest_document(client, tenant_headers, tmp_path, title="Unrelated Report")

    response = client.post(
        "/api/v1/documents/search", headers=tenant_headers, json={"text": "Alpha"}
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["document"]["title"] == "Alpha Widget Spec"


def test_search_filters_by_document_type_and_tags(client, tenant_headers, tmp_path: Path) -> None:
    _ingest_document(
        client,
        tenant_headers,
        tmp_path,
        title="SDS Doc",
        document_type="sds",
        tags="regulated,hazmat",
    )
    _ingest_document(
        client,
        tenant_headers,
        tmp_path,
        title="Datasheet Doc",
        document_type="datasheet",
        tags="internal",
    )

    response = client.post(
        "/api/v1/documents/search",
        headers=tenant_headers,
        json={"document_type": "sds"},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["document"]["document_type"] == "sds"

    response = client.post(
        "/api/v1/documents/search",
        headers=tenant_headers,
        json={"tags": ["hazmat"]},
    )
    items = response.json()["items"]
    assert len(items) == 1
    assert "hazmat" in items[0]["document"]["tags"]


def test_search_by_single_field_filter(client, container, tenant_headers, tmp_path: Path) -> None:
    ingested = _ingest_document(client, tenant_headers, tmp_path, title="Batch Doc")
    _run_async(
        _seed_run(
            container,
            tenant_key="demo",
            document_id=ingested["document_id"],
            version_id=ingested["version_id"],
            fields=[("lot_number", "LOT-42")],
        )
    )
    other = _ingest_document(client, tenant_headers, tmp_path, title="Other Doc")
    _run_async(
        _seed_run(
            container,
            tenant_key="demo",
            document_id=other["document_id"],
            version_id=other["version_id"],
            fields=[("lot_number", "LOT-99")],
        )
    )

    response = client.post(
        "/api/v1/documents/search",
        headers=tenant_headers,
        json={"field_filters": [{"name": "lot_number", "operator": "eq", "value": "LOT-42"}]},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["document"]["document_id"] == ingested["document_id"]
    matched = items[0]["matched_fields"]
    assert len(matched) == 1
    assert matched[0]["name"] == "lot_number"
    assert matched[0]["value"] == "LOT-42"


def test_search_multiple_field_filters_require_each_satisfied_independently(
    client, container, tenant_headers, tmp_path: Path
) -> None:
    """Two filters on different field names must each match -- not force one
    row to satisfy both predicates at once."""
    matches_both = _ingest_document(client, tenant_headers, tmp_path, title="Matches Both")
    _run_async(
        _seed_run(
            container,
            tenant_key="demo",
            document_id=matches_both["document_id"],
            version_id=matches_both["version_id"],
            fields=[("batch_number", "B-1"), ("lot_number", "L-1")],
        )
    )
    matches_one = _ingest_document(client, tenant_headers, tmp_path, title="Matches One")
    _run_async(
        _seed_run(
            container,
            tenant_key="demo",
            document_id=matches_one["document_id"],
            version_id=matches_one["version_id"],
            fields=[("batch_number", "B-1")],
        )
    )

    response = client.post(
        "/api/v1/documents/search",
        headers=tenant_headers,
        json={
            "field_filters": [
                {"name": "batch_number", "operator": "eq", "value": "B-1"},
                {"name": "lot_number", "operator": "eq", "value": "L-1"},
            ]
        },
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["document"]["document_id"] == matches_both["document_id"]
    matched_names = {field["name"] for field in items[0]["matched_fields"]}
    assert matched_names == {"batch_number", "lot_number"}


def test_search_numeric_range_field_filter(
    client, container, tenant_headers, tmp_path: Path
) -> None:
    low = _ingest_document(client, tenant_headers, tmp_path, title="Low Purity")
    _run_async(
        _seed_run(
            container,
            tenant_key="demo",
            document_id=low["document_id"],
            version_id=low["version_id"],
            fields=[("purity_percentage", 50.0)],
        )
    )
    high = _ingest_document(client, tenant_headers, tmp_path, title="High Purity")
    _run_async(
        _seed_run(
            container,
            tenant_key="demo",
            document_id=high["document_id"],
            version_id=high["version_id"],
            fields=[("purity_percentage", 99.5)],
        )
    )

    response = client.post(
        "/api/v1/documents/search",
        headers=tenant_headers,
        json={"field_filters": [{"name": "purity_percentage", "operator": "gte", "value": 90}]},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["document"]["document_id"] == high["document_id"]


def test_search_never_returns_unauthorized_documents(container) -> None:
    """Direct service-level check that ABAC filtering is never bypassed --
    the two documents differ only in required_clearance, and the default
    demo-tenant subject only clears required_clearance<=1 (see
    application.authorization.service.subject_from_tenant).
    """
    from graph_rag.domain.document_search.models import DocumentSearchQuery
    from graph_rag.domain.ingestion.records import DocumentRecord

    async def run() -> None:
        tenant = await container.resolve_tenant(tenant_key="demo")
        document_repo = container.require_document_repo()
        allowed = await document_repo.create_document(
            tenant,
            DocumentRecord(
                document_id=new_id(),
                tenant_id=tenant.tenant_id,
                title="Visible Doc",
                required_clearance=1,
            ),
        )
        denied = await document_repo.create_document(
            tenant,
            DocumentRecord(
                document_id=new_id(),
                tenant_id=tenant.tenant_id,
                title="Restricted Doc",
                required_clearance=9,
            ),
        )

        result = await container.require_document_search().search(
            tenant, DocumentSearchQuery(text=None)
        )
        ids = {hit.document.document_id for hit in result.items}
        assert allowed.document_id in ids
        assert denied.document_id not in ids

    _run_async(run())
