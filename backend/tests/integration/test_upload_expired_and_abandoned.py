"""An expired session releases quotas and leaves no document or outbox row."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from graph_rag.domain.ingestion.upload_session import UploadSessionStatus
from graph_rag.infrastructure.observability.metrics import get_metrics
from graph_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore
from graph_rag.infrastructure.persistence.postgres.repositories import SqlAlchemyDocumentRepository
from graph_rag.infrastructure.persistence.postgres.repositories.upload_sessions import (
    SqlAlchemyUploadSessionRepository,
)
from graph_rag.shared.exceptions import ConflictError
from tests.integration.upload_flow import build_service, tenant_with_quota


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expired_session_has_no_document_or_outbox(session) -> None:
    expired_before = get_metrics().counters.get("upload_sessions_expired_total", 0)
    rejected_before = get_metrics().counters.get("upload_sessions_rejected_total", 0)
    store = InMemoryObjectStore()
    tenant, quotas = tenant_with_quota()
    service, outbox = build_service(session, store, quotas)
    created = await service.create(tenant, filename="old.pdf", byte_size=8)
    record = await SqlAlchemyUploadSessionRepository(session).get(tenant, created.upload_id)
    assert record is not None
    record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await SqlAlchemyUploadSessionRepository(session).save(record)
    with pytest.raises(ConflictError):
        await service.complete(tenant, created.upload_id)
    saved = await SqlAlchemyUploadSessionRepository(session).get(tenant, created.upload_id)
    assert saved is not None
    assert saved.status in {UploadSessionStatus.EXPIRED, UploadSessionStatus.REJECTED}
    docs, _ = await SqlAlchemyDocumentRepository(session).list_documents(tenant, limit=10, offset=0)
    assert docs == []
    assert await outbox.list_unpublished() == []
    assert saved.final_object_key is None
    counters = get_metrics().counters
    assert (
        counters.get("upload_sessions_expired_total", 0)
        + counters.get("upload_sessions_rejected_total", 0)
        >= expired_before + rejected_before + 1
    )
