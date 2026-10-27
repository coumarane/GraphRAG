"""Reprocess keeps the accepted original and does not create a second document."""

from __future__ import annotations

import pytest

from graph_rag.application.deletion.reindex import ReindexDocumentService
from graph_rag.domain.deletion.stages import ReindexScope
from graph_rag.domain.storage.object_keys import staging_object_key
from graph_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore
from graph_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyIngestionRepository,
)
from tests.integration.upload_flow import build_service, tenant_with_quota

PAYLOAD = b"%PDF-1.4\nHi\n"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reprocess_keeps_one_original(session) -> None:
    store = InMemoryObjectStore()
    tenant, quotas = tenant_with_quota()
    service, _outbox = build_service(session, store, quotas)
    created = await service.create(tenant, filename="notes.pdf", byte_size=len(PAYLOAD))
    staging = staging_object_key(
        tenant_id=tenant.tenant_id,
        upload_id=created.upload_id,
        filename="notes.pdf",
    )
    await store.put_bytes(
        tenant,
        object_key=staging,
        data=PAYLOAD,
        content_type="application/pdf",
        content_hash="e" * 64,
    )
    done = await service.complete(tenant, created.upload_id)
    documents = SqlAlchemyDocumentRepository(session)
    version = await documents.get_version(tenant, done.version_id)
    assert version is not None and version.original_object_key is not None
    before = await store.get_bytes(tenant, object_key=version.original_object_key)
    reindex = ReindexDocumentService(
        documents,
        SqlAlchemyIngestionRepository(session),
        object_store=store,
    )
    result = await reindex.execute(
        tenant,
        document_id=done.document_id,
        scope=ReindexScope.GRAPH,
    )
    listed, total = await documents.list_documents(tenant, limit=20, offset=0)
    active = [item for item in listed if item.document_id == done.document_id]
    assert total == 1
    assert len(active) == 1
    assert result.version_id == done.version_id
    assert result.ingestion_run_id != done.ingestion_run_id
    assert await store.get_bytes(tenant, object_key=version.original_object_key) == before
