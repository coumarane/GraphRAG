"""A failed document lists a safe reason, and retry does not upload a second original."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from graph_rag.api.routes.documents import list_documents
from graph_rag.application.deletion.reindex import ReindexDocumentService
from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.domain.deletion.stages import ReindexScope
from graph_rag.domain.ingestion.stages import (
    DocumentLifecycleStatus,
    IngestionRunStatus,
    StageStatus,
)
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
async def test_failed_list_names_the_step_and_retry_reuses_the_original(session) -> None:
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
        content_hash="f" * 64,
    )
    done = await service.complete(tenant, created.upload_id)
    documents = SqlAlchemyDocumentRepository(session)
    runs = SqlAlchemyIngestionRepository(session)
    document = await documents.get_document(tenant, done.document_id)
    assert document is not None
    document.status = DocumentLifecycleStatus.FAILED
    await documents.update_document(tenant, document)
    run = await runs.get_run(tenant, done.ingestion_run_id)
    assert run is not None
    run.status = IngestionRunStatus.FAILED
    run.error_code = "parse_failed"
    run.error_message = "The file could not be parsed"
    run.completed_at = datetime.now(UTC)
    await runs.update_run(tenant, run)
    stages = await runs.list_stages(tenant, run.ingestion_run_id)
    stages[0].status = StageStatus.FAILED
    await runs.update_stage(tenant, stages[0])
    version = await documents.get_version(tenant, done.version_id)
    assert version is not None and version.original_object_key is not None
    original = await store.get_bytes(tenant, object_key=version.original_object_key)

    container = ServiceContainer(document_repo=documents, ingestion_repo=runs)
    listed = await list_documents(tenant, container, offset=0, limit=20)
    assert listed.total == 1
    item = listed.items[0]
    assert item.tenant_id == tenant.tenant_id
    assert item.document_id == done.document_id
    assert item.failed_stage == stages[0].stage.value
    assert item.failure_reason == "The file could not be parsed"
    assert item.failed_at is not None

    result = await ReindexDocumentService(documents, runs, object_store=store).execute(
        tenant,
        document_id=done.document_id,
        scope=ReindexScope.GRAPH,
    )
    again, total = await documents.list_documents(tenant, limit=20, offset=0)
    assert total == 1
    assert again[0].document_id == done.document_id
    assert result.ingestion_run_id != done.ingestion_run_id
    assert await store.get_bytes(tenant, object_key=version.original_object_key) == original
