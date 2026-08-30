"""``GET /documents`` must not resurrect deleted documents in the list.

Regression test: the route returned every document regardless of status,
so a document a user had just deleted (via ``DELETE /documents/{id}``)
kept showing up in the Documents list with active Reprocess/Delete
buttons, as if nothing had happened.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from graph_rag.api.app import create_app
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.ingestion.records import DocumentRecord, DocumentVersionRecord
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus


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
    return {"X-Tenant-Key": "demo", "X-Correlation-ID": str(new_id())}


@pytest.mark.asyncio
async def test_list_documents_excludes_deleted(client, container, tenant_headers) -> None:
    tenant = await container.resolve_tenant(tenant_key="demo")
    document_id = new_id()
    version_id = new_id()
    assert container.document_repo is not None
    await container.document_repo.create_document(
        tenant,
        DocumentRecord(
            document_id=document_id,
            tenant_id=tenant.tenant_id,
            title="seeded",
            status=DocumentLifecycleStatus.READY,
            current_version_id=version_id,
        ),
    )
    await container.document_repo.create_version(
        tenant,
        DocumentVersionRecord(
            version_id=version_id,
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_number=1,
            source_filename="r.pdf",
            mime_type="application/pdf",
            content_hash=content_sha256_hex("r"),
            status=DocumentLifecycleStatus.READY,
        ),
    )
    document_id_str = str(document_id)

    listed = client.get("/api/v1/documents", headers=tenant_headers)
    assert listed.status_code == 200, listed.text
    assert document_id_str in {item["document_id"] for item in listed.json()["items"]}

    deleted = client.delete(f"/api/v1/documents/{document_id_str}", headers=tenant_headers)
    assert deleted.status_code == 202, deleted.text

    after_delete = client.get("/api/v1/documents", headers=tenant_headers)
    assert after_delete.status_code == 200, after_delete.text
    assert document_id_str not in {item["document_id"] for item in after_delete.json()["items"]}
