"""An accepted original stays byte-for-byte stable, including after a worker check."""

from __future__ import annotations

import pytest

from graph_rag.domain.ingestion.retry import IngestionTaskMessage
from graph_rag.domain.storage.object_keys import staging_object_key
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.dead_letters import InMemoryDeadLetterStore
from graph_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore
from graph_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyIngestionRepository,
)
from graph_rag.infrastructure.persistence.redis.memory_stream import InMemoryStreamIngestionQueue
from graph_rag.infrastructure.workers import IngestionWorker
from graph_rag.shared.exceptions import ValidationError
from tests.integration.upload_flow import build_service, tenant_with_quota

PAYLOAD = b"%PDF-1.4\nHi\n"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_url_and_worker_cannot_replace_the_accepted_original(session) -> None:
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
        content_hash="c" * 64,
    )
    done = await service.complete(tenant, created.upload_id)
    version = await SqlAlchemyDocumentRepository(session).get_version(tenant, done.version_id)
    assert version is not None and version.original_object_key is not None
    final_key = version.original_object_key
    original = await store.get_bytes(tenant, object_key=final_key)

    await store.put_bytes(
        tenant,
        object_key=staging,
        data=b"%PDF-1.4\nchanged\n",
        content_type="application/pdf",
        content_hash="d" * 64,
    )
    assert await store.get_bytes(tenant, object_key=final_key) == original
    with pytest.raises(ValidationError):
        await store.put_bytes(
            tenant,
            object_key=final_key,
            data=b"%PDF-1.4\nchanged\n",
            content_type="application/pdf",
            content_hash="d" * 64,
        )

    store.etags[final_key] = "changed-etag"
    letters = InMemoryDeadLetterStore()
    queue = InMemoryStreamIngestionQueue()
    run = await SqlAlchemyIngestionRepository(session).get_run(tenant, done.ingestion_run_id)
    assert run is not None

    async def load_run(_tenant, _run_id):
        stages = await SqlAlchemyIngestionRepository(session).list_stages(
            tenant, done.ingestion_run_id
        )
        return run, stages

    async def persist(_tenant, updated, _stages) -> None:
        await SqlAlchemyIngestionRepository(session).update_run(tenant, updated)

    async def verify(member: TenantContext, current) -> str | None:
        pinned = await SqlAlchemyDocumentRepository(session).get_version(member, current.version_id)
        if pinned is None or not pinned.original_object_key or not pinned.etag:
            return None
        head = await store.head_object(member, object_key=pinned.original_object_key)
        if head.byte_size != (pinned.byte_size or 0) or head.etag != pinned.etag:
            return "object_changed"
        return None

    await queue.enqueue(
        IngestionTaskMessage(
            tenant_id=tenant.tenant_id,
            ingestion_run_id=run.ingestion_run_id,
            document_id=done.document_id,
            version_id=done.version_id,
            content_hash="c" * 64,
            config_fingerprint="fp",
        )
    )
    worker = IngestionWorker(
        queue=queue,
        dead_letter_store=letters,
        load_run=load_run,
        persist_run=persist,
        verify_original=verify,
    )
    tick = await worker.process_one()
    assert tick.acknowledged is True
    assert letters.records[0].error_code == "object_changed"
    assert await store.get_bytes(tenant, object_key=final_key) == original
