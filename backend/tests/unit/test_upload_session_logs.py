"""Session logs name the tenant and ids and omit the write URL and bytes."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from graph_rag.domain.storage.object_keys import staging_object_key
from graph_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore
from graph_rag.infrastructure.persistence.postgres.base import Base
from graph_rag.infrastructure.persistence.postgres.models.uploads import (
    UploadSessionModel,  # noqa: F401
)
from tests.integration.upload_flow import build_service, tenant_with_quota


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


@pytest.mark.asyncio
async def test_logs_omit_urls_and_bytes(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    store = InMemoryObjectStore()
    tenant, quotas = tenant_with_quota()
    service, _outbox = build_service(session, store, quotas)
    with caplog.at_level(logging.INFO):
        created = await service.create(tenant, filename="notes.pdf", byte_size=12)
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
        await service.complete(tenant, created.upload_id)
    text = caplog.text
    assert str(tenant.tenant_id) in text
    assert str(created.upload_id) in text
    assert "method=PUT" not in text
    assert "X-Amz-Signature" not in text
    assert payload.decode() not in text
