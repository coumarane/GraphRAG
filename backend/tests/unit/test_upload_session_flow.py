"""Direct upload acceptance without creating a document early."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from graph_rag.application.ingestion.upload_session import UploadSessionService
from graph_rag.application.quotas.service import InMemoryQuotaService
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.upload_session import UploadSessionStatus
from graph_rag.domain.storage.object_keys import staging_object_key
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore
from graph_rag.infrastructure.persistence.outbox import InMemoryOutboxStore
from graph_rag.infrastructure.persistence.postgres.base import Base
from graph_rag.infrastructure.persistence.postgres.models.uploads import (
    UploadSessionModel,  # noqa: F401
)
from graph_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyIngestionRepository,
    SqlAlchemyTenantRepository,
)
from graph_rag.infrastructure.persistence.postgres.repositories.upload_sessions import (
    SqlAlchemyUploadSessionRepository,
)
from graph_rag.shared.exceptions import ConflictError, ValidationError


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


def _service(
    session: AsyncSession,
    store: InMemoryObjectStore,
    quotas: InMemoryQuotaService,
) -> UploadSessionService:
    return UploadSessionService(
        sessions=SqlAlchemyUploadSessionRepository(session),
        tenant_repo=SqlAlchemyTenantRepository(session),
        document_repo=SqlAlchemyDocumentRepository(session),
        ingestion_repo=SqlAlchemyIngestionRepository(session),
        object_store=store,
        quotas=quotas,
        outbox=InMemoryOutboxStore(),
    )


@pytest.mark.asyncio
async def test_complete_creates_one_document_and_pins_etag(session: AsyncSession) -> None:
    store = InMemoryObjectStore()
    quotas = InMemoryQuotaService()
    tenant_id = new_id()
    quotas.assign_default(tenant_id=tenant_id)
    tenant = TenantContext(tenant_id=tenant_id, tenant_key="demo", user_id=new_id())
    service = _service(session, store, quotas)
    created = await service.create(
        tenant,
        filename="notes.pdf",
        byte_size=12,
        title="Meeting notes",
    )
    assert created.upload_url is not None
    assert "method=PUT" in created.upload_url
    key = staging_object_key(
        tenant_id=tenant.tenant_id,
        upload_id=created.upload_id,
        filename="notes.pdf",
    )
    payload = b"%PDF-1.4\nHi\n"
    await store.put_bytes(
        tenant,
        object_key=key,
        data=payload,
        content_type="application/pdf",
        content_hash="a" * 64,
    )
    done = await service.complete(tenant, created.upload_id)
    docs, _ = await SqlAlchemyDocumentRepository(session).list_documents(tenant, limit=10, offset=0)
    assert len(docs) == 1
    assert docs[0].title == "Meeting notes"
    assert docs[0].document_id == done.document_id
    again = await service.complete(tenant, created.upload_id)
    assert again.ingestion_run_id == done.ingestion_run_id
    version = await SqlAlchemyDocumentRepository(session).get_version(tenant, done.version_id)
    assert version is not None and version.etag
    assert version.original_object_key not in (key,)
    await store.put_bytes(
        tenant,
        object_key=key,
        data=b"%PDF-1.4\nchanged\n",
        content_type="application/pdf",
        content_hash="b" * 64,
    )
    final = await store.get_bytes(tenant, object_key=version.original_object_key or "")
    assert final == payload


@pytest.mark.asyncio
async def test_empty_object_leaves_no_document(session: AsyncSession) -> None:
    store = InMemoryObjectStore()
    quotas = InMemoryQuotaService()
    tenant_id = new_id()
    quotas.assign_default(tenant_id=tenant_id)
    tenant = TenantContext(tenant_id=tenant_id, tenant_key="demo")
    service = _service(session, store, quotas)
    created = await service.create(tenant, filename="empty.pdf", byte_size=1)
    key = staging_object_key(
        tenant_id=tenant.tenant_id,
        upload_id=created.upload_id,
        filename="empty.pdf",
    )
    store.objects[key] = b""
    with pytest.raises(ValidationError):
        await service.complete(tenant, created.upload_id)
    docs, _ = await SqlAlchemyDocumentRepository(session).list_documents(tenant, limit=10, offset=0)
    assert docs == []
    record = await SqlAlchemyUploadSessionRepository(session).get(tenant, created.upload_id)
    assert record is not None
    assert record.status is UploadSessionStatus.REJECTED


@pytest.mark.asyncio
async def test_oversized_declaration_creates_no_session(session: AsyncSession) -> None:
    store = InMemoryObjectStore()
    quotas = InMemoryQuotaService()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    service = _service(session, store, quotas)
    with pytest.raises(ValidationError):
        await service.create(tenant, filename="big.pdf", byte_size=104_857_601)


@pytest.mark.asyncio
async def test_expired_session_releases_and_keeps_no_document(session: AsyncSession) -> None:
    store = InMemoryObjectStore()
    quotas = InMemoryQuotaService()
    tenant_id = new_id()
    quotas.assign_default(tenant_id=tenant_id)
    tenant = TenantContext(tenant_id=tenant_id, tenant_key="demo")
    service = _service(session, store, quotas)
    created = await service.create(tenant, filename="old.pdf", byte_size=8)
    record = await SqlAlchemyUploadSessionRepository(session).get(tenant, created.upload_id)
    assert record is not None
    record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await SqlAlchemyUploadSessionRepository(session).save(record)
    with pytest.raises(ConflictError):
        await service.complete(tenant, created.upload_id)
    docs, _ = await SqlAlchemyDocumentRepository(session).list_documents(tenant, limit=10, offset=0)
    assert docs == []
