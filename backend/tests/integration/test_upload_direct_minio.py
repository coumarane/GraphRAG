"""A 100 MB browser PUT lands in MinIO, not in the Next.js ingest route."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest

from graph_rag.config.settings import MinioSettings
from graph_rag.infrastructure.persistence.minio.object_store import MinioObjectStore
from tests.integration.upload_flow import build_service, tenant_with_quota

SIZE = 100 * 1024 * 1024
PAGE = Path(__file__).resolve().parents[3] / "frontend/src/app/upload/page.tsx"


def _write_pdf(path: Path, size: int) -> None:
    prefix = b"%PDF-1.4\n"
    with path.open("wb") as handle:
        handle.write(prefix)
        handle.seek(size - 1)
        handle.write(b"\n")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hundred_megabyte_put_finishes_within_30_seconds(
    compose_minio: None, tmp_path: Path
) -> None:
    _ = compose_minio
    page = PAGE.read_text()
    assert "/api/documents/uploads" in page
    assert '"/api/ingest"' not in page
    assert "`/api/ingest`" not in page
    store = MinioObjectStore(MinioSettings())
    await store.ensure_bucket()
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from graph_rag.infrastructure.persistence.postgres.base import Base
    from graph_rag.infrastructure.persistence.postgres.models.uploads import (  # noqa: F401
        UploadSessionModel,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        tenant, quotas = tenant_with_quota()
        service, _outbox = build_service(session, store, quotas)
        created = await service.create(tenant, filename="large.pdf", byte_size=SIZE)
        assert created.upload_url is not None
        path = tmp_path / "large.pdf"
        _write_pdf(path, SIZE)
        started = time.monotonic()

        def _put() -> tuple[str | None, int]:
            with httpx.Client(timeout=60) as client:
                preflight = client.options(
                    created.upload_url,
                    headers={
                        "Origin": "http://localhost:3000",
                        "Access-Control-Request-Method": "PUT",
                    },
                )
                with path.open("rb") as handle:
                    put = client.put(created.upload_url, content=handle)
            origin = preflight.headers.get("access-control-allow-origin")
            return origin, put.status_code

        origin, status = await asyncio.to_thread(_put)
        assert origin == "http://localhost:3000"
        assert status in {200, 204}
        done = await service.complete(tenant, created.upload_id)
        assert time.monotonic() - started < 30
        assert done.document_id
    await engine.dispose()
