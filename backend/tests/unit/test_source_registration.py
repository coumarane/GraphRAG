"""Local source loader and registration use-case tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from enterprise_rag.application.ingestion import RegisterSourceRequest, RegisterSourceService
from enterprise_rag.domain.ids import content_sha256_hex, new_id
from enterprise_rag.domain.storage.protocols import StoredObject
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.intake.source_loader import DefaultSourceLoader
from enterprise_rag.infrastructure.persistence.postgres.base import Base
from enterprise_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyIngestionRepository,
    SqlAlchemyTenantRepository,
)
from enterprise_rag.shared.exceptions import ConflictError


class InMemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.bucket = "enterprise-rag"

    async def ensure_bucket(self) -> None:
        return None

    async def put_bytes(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        content_hash: str,
    ) -> StoredObject:
        self.objects[object_key] = data
        return StoredObject(
            bucket=self.bucket,
            object_key=object_key,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=len(data),
            etag="etag",
        )

    async def get_bytes(self, tenant: TenantContext, *, object_key: str) -> bytes:
        return self.objects[object_key]

    async def delete_prefix(self, tenant: TenantContext, *, prefix: str) -> int:
        keys = [key for key in self.objects if key.startswith(prefix)]
        for key in keys:
            del self.objects[key]
        return len(keys)

    async def presign_get(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        expires_seconds: int = 300,
    ) -> str:
        return f"https://example.invalid/{object_key}?exp={expires_seconds}"


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
async def test_load_local_pdf(tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-1.4\n%EOF\n")
    loader = DefaultSourceLoader(max_upload_bytes=10_000)
    source = await loader.load_local(str(path))
    assert source.mime_type == "application/pdf"
    assert source.filename == "sample.pdf"
    assert loader.hash_content(source.content) == content_sha256_hex(source.content)


@pytest.mark.asyncio
async def test_register_source_stores_original(session: AsyncSession, tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    content = b"%PDF-1.7\nhello\n"
    path.write_bytes(content)

    store = InMemoryObjectStore()
    service = RegisterSourceService(
        tenant_repo=SqlAlchemyTenantRepository(session),
        document_repo=SqlAlchemyDocumentRepository(session),
        ingestion_repo=SqlAlchemyIngestionRepository(session),
        object_store=store,
        source_loader=DefaultSourceLoader(max_upload_bytes=10_000),
    )
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    result = await service.execute(
        tenant,
        RegisterSourceRequest(local_path=str(path), title="Doc"),
    )
    await session.commit()

    assert result.mime_type == "application/pdf"
    assert result.byte_size == len(content)
    assert result.content_hash == content_sha256_hex(content)
    assert result.original_object_key in store.objects
    assert result.duplicate_version is False

    # Second registration with same bytes is rejected (tenant-wide).
    with pytest.raises(ConflictError) as exc_info:
        await service.execute(
            tenant,
            RegisterSourceRequest(local_path=str(path)),
        )
    assert exc_info.value.details["document_id"] == str(result.document_id)
    assert exc_info.value.details["version_id"] == str(result.version_id)

    # force_new_version allows re-registering identical content.
    forced = await service.execute(
        tenant,
        RegisterSourceRequest(
            local_path=str(path),
            document_id=result.document_id,
            force_new_version=True,
        ),
    )
    assert forced.duplicate_version is False
    assert forced.version_id != result.version_id
    assert forced.document_id == result.document_id
