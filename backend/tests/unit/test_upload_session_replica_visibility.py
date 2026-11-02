"""Create must commit before the browser can complete on another API replica.

The API process keeps one database session. ``create`` used to flush the
upload row and return the presigned URL without ``commit_db()``. The browser
then PUT the bytes to Azure and POSTed complete, which the service load-balanced
onto the other replica. That replica's transaction could not see the
uncommitted row and returned ``Upload session not found``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from graph_rag.api.routes.documents import (
    UploadCompleteRequest,
    UploadCreateRequest,
    complete_upload_session,
    create_upload_session,
)
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.ids import new_id
from graph_rag.domain.storage.object_keys import staging_object_key
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.object_store import InMemoryObjectStore
from graph_rag.infrastructure.persistence.postgres.base import Base
from graph_rag.infrastructure.persistence.postgres.models.uploads import (  # noqa: F401
    UploadSessionModel,
)
from graph_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyIngestionRepository,
    SqlAlchemyTenantRepository,
)
from graph_rag.infrastructure.persistence.postgres.repositories.upload_sessions import (
    SqlAlchemyUploadSessionRepository,
)
from graph_rag.shared.exceptions import NotFoundError

_PDF = b"%PDF-1.4\nHi\n"


def _container(session, store):
    async def _commit() -> None:
        await session.commit()

    container = build_local_container(
        object_store=store,
        tenant_repo=SqlAlchemyTenantRepository(session),
        document_repo=SqlAlchemyDocumentRepository(session),
        ingestion_repo=SqlAlchemyIngestionRepository(session),
        on_commit=_commit,
    )
    container.upload_session_repo = SqlAlchemyUploadSessionRepository(session)
    container.db_session = session
    return container


@pytest.mark.asyncio
async def test_other_replica_completes_after_azure_put(tmp_path: Path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'uploads.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = InMemoryObjectStore()
    session_a = factory()
    session_b = factory()
    tenant = TenantContext(
        tenant_id=new_id(),
        tenant_key="demo",
        user_id=new_id(),
        roles=("admin",),
    )
    try:
        created = await create_upload_session(
            UploadCreateRequest(filename="notes.pdf", byte_size=len(_PDF), title="Notes"),
            tenant,
            _container(session_a, store),
        )
        key = staging_object_key(
            tenant_id=tenant.tenant_id,
            upload_id=created.upload_id,
            filename="notes.pdf",
        )
        await store.put_bytes(
            tenant,
            object_key=key,
            data=_PDF,
            content_type="application/pdf",
            content_hash="a" * 64,
        )
        try:
            completed = await complete_upload_session(
                created.upload_id,
                tenant,
                _container(session_b, store),
                UploadCompleteRequest(title="Notes"),
            )
        except NotFoundError as exc:
            pytest.fail(f"Upload session not found on the other replica: {exc}")
        assert completed.document_id
        assert completed.status == "accepted"
    finally:
        await session_a.close()
        await session_b.close()
        await engine.dispose()
