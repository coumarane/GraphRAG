"""A second tenant cannot see or complete the first tenant's upload."""

from __future__ import annotations

import pytest

from graph_rag.application.deletion.reindex import ReindexDocumentService
from graph_rag.domain.deletion.stages import ReindexScope
from graph_rag.domain.ids import new_id
from graph_rag.domain.storage.object_keys import staging_object_key
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore
from graph_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyIngestionRepository,
)
from graph_rag.infrastructure.persistence.postgres.repositories.upload_sessions import (
    SqlAlchemyUploadSessionRepository,
)
from graph_rag.shared.exceptions import NotFoundError, TenantError, ValidationError
from tests.integration.upload_flow import build_service, tenant_with_quota


@pytest.mark.integration
@pytest.mark.asyncio
async def test_foreign_tenant_is_refused(session) -> None:
    store = InMemoryObjectStore()
    owner, quotas = tenant_with_quota()
    other = TenantContext(tenant_id=new_id(), tenant_key="other", user_id=new_id())
    quotas.assign_default(tenant_id=other.tenant_id)
    service, _outbox = build_service(session, store, quotas)
    created = await service.create(owner, filename="notes.pdf", byte_size=12)
    key = staging_object_key(
        tenant_id=owner.tenant_id, upload_id=created.upload_id, filename="notes.pdf"
    )
    await store.put_bytes(
        owner,
        object_key=key,
        data=b"%PDF-1.4\nHi\n",
        content_type="application/pdf",
        content_hash="a" * 64,
    )
    with pytest.raises((NotFoundError, TenantError)):
        await SqlAlchemyUploadSessionRepository(session).get(other, created.upload_id)
    with pytest.raises((NotFoundError, TenantError)):
        await service.complete(other, created.upload_id)
    with pytest.raises(ValidationError):
        await store.presign_put(
            other,
            object_key=key,
            expires_seconds=60,
        )
    docs, _ = await SqlAlchemyDocumentRepository(session).list_documents(other, limit=10, offset=0)
    assert docs == []
    done = await service.complete(owner, created.upload_id)
    try:
        foreign = await SqlAlchemyDocumentRepository(session).get_document(
            other, done.document_id
        )
    except (NotFoundError, TenantError):
        foreign = None
    assert foreign is None
    runs = SqlAlchemyIngestionRepository(session)
    assert await runs.get_run(other, done.ingestion_run_id) is None
    with pytest.raises((NotFoundError, TenantError)):
        await ReindexDocumentService(
            SqlAlchemyDocumentRepository(session),
            runs,
            object_store=store,
        ).execute(other, document_id=done.document_id, scope=ReindexScope.GRAPH)
