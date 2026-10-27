"""Empty, oversized, and disallowed uploads leave no document or outbox row."""

from __future__ import annotations

import pytest

from graph_rag.domain.ingestion.upload_session import UploadSessionStatus
from graph_rag.domain.storage.object_keys import staging_object_key
from graph_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore
from graph_rag.infrastructure.persistence.postgres.repositories import SqlAlchemyDocumentRepository
from graph_rag.infrastructure.persistence.postgres.repositories.upload_sessions import (
    SqlAlchemyUploadSessionRepository,
)
from graph_rag.shared.exceptions import UnsupportedDocumentError, ValidationError
from tests.integration.upload_flow import build_service, tenant_with_quota


@pytest.mark.integration
@pytest.mark.asyncio
async def test_empty_oversize_and_disallowed_mime(session) -> None:
    store = InMemoryObjectStore()
    tenant, quotas = tenant_with_quota()
    service, outbox = build_service(session, store, quotas)
    with pytest.raises(ValidationError):
        await service.create(tenant, filename="big.pdf", byte_size=104_857_601)

    created = await service.create(tenant, filename="empty.pdf", byte_size=1)
    key = staging_object_key(
        tenant_id=tenant.tenant_id, upload_id=created.upload_id, filename="empty.pdf"
    )
    store.objects[key] = b""
    with pytest.raises(ValidationError):
        await service.complete(tenant, created.upload_id)

    bad = await service.create(tenant, filename="virus.exe", byte_size=4)
    bad_key = staging_object_key(
        tenant_id=tenant.tenant_id, upload_id=bad.upload_id, filename="virus.exe"
    )
    await store.put_bytes(
        tenant,
        object_key=bad_key,
        data=b"MZ\x90\x00",
        content_type="application/octet-stream",
        content_hash="c" * 64,
    )
    with pytest.raises(UnsupportedDocumentError):
        await service.complete(tenant, bad.upload_id)
    saved = await SqlAlchemyUploadSessionRepository(session).get(tenant, bad.upload_id)
    assert saved is not None
    assert saved.status is UploadSessionStatus.REJECTED
    docs, _ = await SqlAlchemyDocumentRepository(session).list_documents(tenant, limit=10, offset=0)
    assert docs == []
    assert await outbox.list_unpublished() == []
    assert all(item.final_object_key is None for item in (saved,))
