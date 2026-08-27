"""DELETE /documents/{id} must commit the Postgres row removal.

Regression: the route called ``submit_deletion`` (which deletes the row in
the process-local SQLAlchemy session) but never ``commit_db()``. With a
shared long-lived session and multiple API replicas, the UI returned 202
while other pods kept listing the document — exactly the "Object not found"
orphans that never disappeared after Delete.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from graph_rag.api.app import create_app
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.ingestion.records import DocumentRecord, DocumentVersionRecord
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus
from graph_rag.shared.exceptions import StorageError


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch):
    from graph_rag.config.settings import clear_settings_cache

    monkeypatch.setenv("AUTH_ENABLED", "false")
    clear_settings_cache()
    commits: list[str] = []

    async def _commit() -> None:
        commits.append("committed")

    try:
        c = build_local_container(on_commit=_commit)
        c._test_commits = commits  # type: ignore[attr-defined]
        yield c
    finally:
        clear_settings_cache()


@pytest.fixture
def client(container):
    return TestClient(create_app(container))


@pytest.fixture
def tenant_headers():
    return {"X-Tenant-Key": "demo", "X-Correlation-ID": str(new_id())}


async def _seed_failed_orphan(container, *, title: str = "Presentation SY-KNP"):
    tenant = await container.resolve_tenant(tenant_key="demo")
    document_id = new_id()
    version_id = new_id()
    assert container.document_repo is not None
    await container.document_repo.create_document(
        tenant,
        DocumentRecord(
            document_id=document_id,
            tenant_id=tenant.tenant_id,
            title=title,
            status=DocumentLifecycleStatus.FAILED,
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
            source_filename="orphan.pdf",
            mime_type="application/pdf",
            content_hash=content_sha256_hex("orphan"),
            status=DocumentLifecycleStatus.FAILED,
            original_object_key=(
                f"tenants/{tenant.tenant_id}/documents/{document_id}/"
                f"versions/{version_id}/original/orphan.pdf"
            ),
        ),
    )
    return tenant, document_id


@pytest.mark.asyncio
async def test_delete_route_commits_db_so_row_is_gone(client, container, tenant_headers) -> None:
    _tenant, document_id = await _seed_failed_orphan(container)
    document_id_str = str(document_id)

    deleted = client.delete(f"/api/v1/documents/{document_id_str}", headers=tenant_headers)
    assert deleted.status_code == 202, deleted.text
    assert "committed" in container._test_commits  # type: ignore[attr-defined]

    remaining = await container.document_repo.get_document(  # type: ignore[union-attr]
        await container.resolve_tenant(tenant_key="demo"),
        document_id,
    )
    assert remaining is None

    listed = client.get("/api/v1/documents", headers=tenant_headers)
    assert listed.status_code == 200
    assert document_id_str not in {item["document_id"] for item in listed.json()["items"]}


@pytest.mark.asyncio
async def test_delete_still_removes_row_when_object_cleanup_fails(
    client, container, tenant_headers
) -> None:
    _tenant, document_id = await _seed_failed_orphan(container)
    assert container.delete_document is not None
    assert container.delete_document.object_store is not None

    async def _boom(tenant, *, prefix: str) -> int:  # noqa: ANN001
        raise StorageError("Object not found", details={"prefix": prefix})

    container.delete_document.object_store.delete_prefix = _boom  # type: ignore[method-assign]

    deleted = client.delete(f"/api/v1/documents/{document_id}", headers=tenant_headers)
    assert deleted.status_code == 202, deleted.text
    body = deleted.json()
    assert any("object_cleanup_failed" in w for w in body.get("warnings", []))

    remaining = await container.document_repo.get_document(  # type: ignore[union-attr]
        await container.resolve_tenant(tenant_key="demo"),
        document_id,
    )
    assert remaining is None
