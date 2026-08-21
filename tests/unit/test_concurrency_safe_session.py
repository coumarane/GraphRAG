"""LockedAsyncProxy must serialize concurrent access to a shared AsyncSession."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.ingestion import DocumentLifecycleStatus, DocumentRecord
from enterprise_rag.domain.ingestion.records import TenantRecord
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.persistence.postgres.base import Base
from enterprise_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyTenantRepository,
)
from enterprise_rag.infrastructure.persistence.postgres.session import LockedAsyncProxy


class _RacyAsyncFake:
    """Fake async object that fails if two calls overlap in-flight.

    Mirrors the real failure mode: asyncpg raises when a second operation
    starts on a connection before the first one finishes.
    """

    def __init__(self) -> None:
        self.busy = False
        self.calls = 0

    async def execute(self, delay: float = 0.01) -> str:
        if self.busy:
            raise RuntimeError("cannot perform operation: another operation is in progress")
        self.busy = True
        self.calls += 1
        try:
            await asyncio.sleep(delay)
            return "ok"
        finally:
            self.busy = False


@pytest.mark.asyncio
async def test_wrapper_serializes_concurrent_calls_on_fake_target() -> None:
    fake = _RacyAsyncFake()
    lock = asyncio.Lock()
    wrapped = LockedAsyncProxy(fake, lock)

    results = await asyncio.gather(*(wrapped.execute() for _ in range(20)))

    assert results == ["ok"] * 20
    assert fake.calls == 20


@pytest.mark.asyncio
async def test_unwrapped_fake_target_actually_races() -> None:
    """Sanity check that the fake reproduces the real race without the wrapper."""
    fake = _RacyAsyncFake()

    with pytest.raises(RuntimeError, match="another operation is in progress"):
        await asyncio.gather(*(fake.execute() for _ in range(20)))


@pytest.fixture
async def raw_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_real_repos_survive_concurrent_writes_when_wrapped(
    raw_session: AsyncSession,
) -> None:
    """Repositories, not the raw session, must be the thing that's locked.

    A repo method like create_document does a sync `session.add()` followed
    by `await session.flush()`. Locking only the session's async methods
    still lets a concurrent coroutine's sync `add()` land mid-flush from
    another coroutine — this test fails without repo-level wrapping.
    """
    lock = asyncio.Lock()
    tenants = LockedAsyncProxy(SqlAlchemyTenantRepository(raw_session), lock)
    documents = LockedAsyncProxy(SqlAlchemyDocumentRepository(raw_session), lock)
    locked_session = LockedAsyncProxy(raw_session, lock)

    tenant = TenantRecord(tenant_id=new_id(), tenant_key="concurrent-tenant")
    await tenants.upsert(tenant)
    await locked_session.commit()
    ctx = TenantContext(tenant_id=tenant.tenant_id, tenant_key="concurrent-tenant")

    async def create_one(i: int) -> None:
        await documents.create_document(
            ctx,
            DocumentRecord(
                document_id=new_id(),
                tenant_id=tenant.tenant_id,
                title=f"doc-{i}",
                status=DocumentLifecycleStatus.REGISTERED,
            ),
        )
        await locked_session.commit()

    await asyncio.gather(*(create_one(i) for i in range(15)))

    items, total = await documents.list_documents(ctx, offset=0, limit=50)
    assert total == 15
    assert {item.title for item in items} == {f"doc-{i}" for i in range(15)}


@pytest.mark.asyncio
async def test_wrapping_only_the_session_still_races_on_sync_add(
    raw_session: AsyncSession,
) -> None:
    """Regression guard: proves session-only wrapping is insufficient.

    If this ever stops raising, someone re-introduced the narrower
    session-only wrapping this test exists to rule out.
    """
    lock = asyncio.Lock()
    locked_session = LockedAsyncProxy(raw_session, lock)
    tenants = SqlAlchemyTenantRepository(locked_session)  # type: ignore[arg-type]
    documents = SqlAlchemyDocumentRepository(locked_session)  # type: ignore[arg-type]

    tenant = TenantRecord(tenant_id=new_id(), tenant_key="concurrent-tenant-2")
    await tenants.upsert(tenant)
    await locked_session.commit()
    ctx = TenantContext(tenant_id=tenant.tenant_id, tenant_key="concurrent-tenant-2")

    async def create_one(i: int) -> None:
        await documents.create_document(
            ctx,
            DocumentRecord(
                document_id=new_id(),
                tenant_id=tenant.tenant_id,
                title=f"doc-{i}",
                status=DocumentLifecycleStatus.REGISTERED,
            ),
        )
        await locked_session.commit()

    with pytest.raises(Exception):  # noqa: B017 — SQLAlchemy warning-as-error or a real DBAPI error
        await asyncio.gather(*(create_one(i) for i in range(15)))
