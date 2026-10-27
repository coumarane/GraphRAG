"""Two 100 MB uploads by one member both reach an acceptance decision."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from graph_rag.config.settings import MinioSettings
from graph_rag.infrastructure.persistence.minio.object_store import MinioObjectStore
from graph_rag.infrastructure.persistence.postgres.base import Base
from graph_rag.infrastructure.persistence.postgres.models.uploads import (
    UploadSessionModel,  # noqa: F401
)
from graph_rag.infrastructure.persistence.postgres.repositories import SqlAlchemyDocumentRepository
from tests.integration.upload_flow import build_service, tenant_with_quota

SIZE = 100 * 1024 * 1024


def _write(path: Path, marker: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(b"%PDF-1.4\n" + marker + b"\n")
        handle.seek(SIZE - 1)
        handle.write(b"\n")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_two_concurrent_hundred_megabyte_uploads(
    compose_minio: None, tmp_path: Path
) -> None:
    _ = compose_minio
    store = MinioObjectStore(MinioSettings())
    await store.ensure_bucket()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        tenant, quotas = tenant_with_quota()
        service, _outbox = build_service(session, store, quotas)
        created_a = await service.create(tenant, filename="a.pdf", byte_size=SIZE)
        created_b = await service.create(tenant, filename="b.pdf", byte_size=SIZE)
        path_a = tmp_path / "a.pdf"
        path_b = tmp_path / "b.pdf"
        await asyncio.gather(
            asyncio.to_thread(_write, path_a, b"alpha"),
            asyncio.to_thread(_write, path_b, b"beta"),
        )

        def _put(url: str, path: Path) -> int:
            with httpx.Client(timeout=60) as client, path.open("rb") as handle:
                response = client.put(url, content=handle)
            return response.status_code

        statuses = await asyncio.gather(
            asyncio.to_thread(_put, created_a.upload_url or "", path_a),
            asyncio.to_thread(_put, created_b.upload_url or "", path_b),
        )
        assert statuses == [200, 200] or set(statuses) <= {200, 204}
        first = await service.complete(tenant, created_a.upload_id)
        second = await service.complete(tenant, created_b.upload_id)
        assert first.document_id != second.document_id
        listed, total = await SqlAlchemyDocumentRepository(session).list_documents(
            tenant, limit=10, offset=0
        )
        assert total == 2
        assert {item.document_id for item in listed} == {first.document_id, second.document_id}
    await engine.dispose()
