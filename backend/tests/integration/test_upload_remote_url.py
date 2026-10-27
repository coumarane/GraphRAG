"""Private URLs are rejected. An allowed HTTPS body uses the same acceptance path."""

from __future__ import annotations

import pytest

from graph_rag.domain.storage.protocols import SourceBytes
from graph_rag.infrastructure.intake.url_fetch import SafeUrlFetcher
from graph_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore
from graph_rag.infrastructure.persistence.postgres.repositories import SqlAlchemyDocumentRepository
from graph_rag.shared.exceptions import ValidationError
from tests.integration.upload_flow import build_service, tenant_with_quota


class _HttpsLoader:
    async def load_url(self, url: str) -> SourceBytes:
        assert url.startswith("https://")
        return SourceBytes(
            filename="notes.pdf",
            mime_type="application/pdf",
            content=b"%PDF-1.4\nHi\n",
            source_uri=url,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_private_url_is_rejected_and_https_is_accepted(session) -> None:
    fetcher = SafeUrlFetcher(max_upload_bytes=104_857_600)
    with pytest.raises(ValidationError):
        await fetcher.fetch("http://127.0.0.1/secret")
    with pytest.raises(ValidationError):
        await fetcher.fetch("https://user:password@example.com/file.pdf")

    store = InMemoryObjectStore()
    tenant, quotas = tenant_with_quota()
    service, outbox = build_service(session, store, quotas, source_loader=_HttpsLoader())
    created = await service.create(
        tenant,
        filename="notes.pdf",
        byte_size=None,
        source_url="https://example.com/notes.pdf",
    )
    done = await service.complete(tenant, created.upload_id)
    docs, _ = await SqlAlchemyDocumentRepository(session).list_documents(tenant, limit=10, offset=0)
    assert len(docs) == 1
    assert docs[0].document_id == done.document_id
    assert await outbox.list_unpublished()
