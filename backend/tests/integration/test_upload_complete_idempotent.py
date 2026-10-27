"""Repeated complete is one run, and the same bytes are refused until the owner is deleted."""

from __future__ import annotations

import pytest

from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus
from graph_rag.domain.storage.object_keys import staging_object_key
from graph_rag.infrastructure.observability.metrics import get_metrics
from graph_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore
from graph_rag.infrastructure.persistence.postgres.repositories import SqlAlchemyDocumentRepository
from graph_rag.shared.exceptions import ConflictError
from tests.integration.upload_flow import build_service, tenant_with_quota

PAYLOAD = b"%PDF-1.4\nHi\n"


async def _put(store, tenant, upload_id: object, filename: str = "notes.pdf") -> None:
    key = staging_object_key(
        tenant_id=tenant.tenant_id,
        upload_id=upload_id,  # type: ignore[arg-type]
        filename=filename,
    )
    await store.put_bytes(
        tenant,
        object_key=key,
        data=PAYLOAD,
        content_type="application/pdf",
        content_hash="a" * 64,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repeat_complete_and_deleted_owner_reupload(session) -> None:
    created_before = get_metrics().counters.get("upload_sessions_created_total", 0)
    completed_before = get_metrics().counters.get("upload_sessions_completed_total", 0)
    store = InMemoryObjectStore()
    tenant, quotas = tenant_with_quota()
    service, outbox = build_service(session, store, quotas)
    created = await service.create(tenant, filename="notes.pdf", byte_size=len(PAYLOAD))
    await _put(store, tenant, created.upload_id)
    done = await service.complete(tenant, created.upload_id)
    again = await service.complete(tenant, created.upload_id)
    assert again.ingestion_run_id == done.ingestion_run_id
    queued = await outbox.list_unpublished()
    assert len(queued) == 1

    second = await service.create(tenant, filename="notes.pdf", byte_size=len(PAYLOAD))
    await _put(store, tenant, second.upload_id)
    with pytest.raises(ConflictError):
        await service.complete(tenant, second.upload_id)
    docs, _ = await SqlAlchemyDocumentRepository(session).list_documents(tenant, limit=10, offset=0)
    assert len([doc for doc in docs if doc.status is not DocumentLifecycleStatus.DELETED]) == 1

    owner = await SqlAlchemyDocumentRepository(session).get_document(tenant, done.document_id)
    assert owner is not None
    owner.status = DocumentLifecycleStatus.DELETED
    await SqlAlchemyDocumentRepository(session).update_document(tenant, owner)
    third = await service.create(tenant, filename="notes-again.pdf", byte_size=len(PAYLOAD))
    await _put(store, tenant, third.upload_id, "notes-again.pdf")
    accepted = await service.complete(tenant, third.upload_id)
    assert accepted.document_id != done.document_id
    assert get_metrics().counters["upload_sessions_created_total"] >= created_before + 3
    assert get_metrics().counters["upload_sessions_completed_total"] >= completed_before + 2
