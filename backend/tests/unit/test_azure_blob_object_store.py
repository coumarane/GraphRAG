"""Azure Blob object-store adapter tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr

from graph_rag.config.settings import AzureBlobSettings
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.azure_blob.object_store import AzureBlobObjectStore


class _FakeBlobClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def upload_blob(
        self,
        data: bytes,
        *,
        overwrite: bool,
        content_settings: Any,
        metadata: dict[str, str],
    ) -> SimpleNamespace:
        self.calls.append(
            {
                "data": data,
                "overwrite": overwrite,
                "content_type": content_settings.content_type,
                "metadata": metadata,
            }
        )
        return SimpleNamespace(etag='"azure-etag"')


class _FakeBlobServiceClient:
    def __init__(self) -> None:
        self.blob_client = _FakeBlobClient()
        self.last_container: str | None = None
        self.last_blob: str | None = None

    def get_blob_client(self, *, container: str, blob: str) -> _FakeBlobClient:
        self.last_container = container
        self.last_blob = blob
        return self.blob_client


class _FakeContentSettings:
    def __init__(self, *, content_type: str) -> None:
        self.content_type = content_type


class _ImportedBlobServiceClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs


_AZURE_MODULE = SimpleNamespace(
    BlobServiceClient=_ImportedBlobServiceClient,
    ContentSettings=_FakeContentSettings,
)


@pytest.mark.asyncio
async def test_put_bytes_uses_azure_safe_metadata_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_service = _FakeBlobServiceClient()

    monkeypatch.setitem(
        __import__("sys").modules,
        "azure.storage.blob",
        SimpleNamespace(
            BlobServiceClient=_ImportedBlobServiceClient,
            ContentSettings=_FakeContentSettings,
        ),
    )

    store = AzureBlobObjectStore(
        AzureBlobSettings(
            account_name="acct",
            account_url="https://acct.blob.core.windows.net",
            container="documents",
            access_key=SecretStr("secret"),
        )
    )
    store._blob_service = fake_service

    tenant = TenantContext(tenant_id=uuid4(), tenant_key="demo")
    object_key = f"tenants/{tenant.tenant_id}/documents/demo.pdf"

    stored = await store.put_bytes(
        tenant,
        object_key=object_key,
        data=b"pdf-bytes",
        content_type="application/pdf",
        content_hash="AB" * 32,
    )

    assert fake_service.last_container == "documents"
    assert fake_service.last_blob == object_key
    assert fake_service.blob_client.calls == [
        {
            "data": b"pdf-bytes",
            "overwrite": True,
            "content_type": "application/pdf",
            "metadata": {
                "content_sha256": "AB" * 32,
                "tenant_id": str(tenant.tenant_id),
            },
        }
    ]
    assert stored.etag == "azure-etag"
    assert stored.content_hash == "ab" * 32


class _RangeBlob:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.ranges: list[tuple[int, int]] = []

    def get_blob_properties(self) -> SimpleNamespace:
        return SimpleNamespace(size=len(self.payload), etag="etag", version_id=None)

    def download_blob(self, *, offset: int, length: int) -> SimpleNamespace:
        self.ranges.append((offset, length))
        chunk = self.payload[offset : offset + length]
        return SimpleNamespace(readall=lambda: chunk)


class _RangeService:
    def __init__(self, payload: bytes) -> None:
        self.blob = _RangeBlob(payload)

    def get_blob_client(self, *args: object, **kwargs: object) -> _RangeBlob:
        _ = args, kwargs
        return self.blob


def _store(service: object) -> tuple[AzureBlobObjectStore, TenantContext, str]:
    store = AzureBlobObjectStore(
        AzureBlobSettings(
            account_name="acct",
            account_url="https://acct.blob.core.windows.net",
            container="documents",
            access_key=SecretStr("secret"),
        )
    )
    store._blob_service = service
    tenant = TenantContext(tenant_id=uuid4(), tenant_key="demo")
    key = f"tenants/{tenant.tenant_id}/uploads/{uuid4()}/staging/notes.pdf"
    return store, tenant, key


@pytest.mark.asyncio
async def test_iter_bytes_reads_one_bounded_range_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"0123456789abcdef"
    service = _RangeService(payload)
    monkeypatch.setitem(
        __import__("sys").modules,
        "azure.storage.blob",
        _AZURE_MODULE,
    )
    store, tenant, key = _store(service)
    chunks = [chunk async for chunk in store.iter_bytes(tenant, object_key=key, chunk_size=4)]
    assert chunks == [b"0123", b"4567", b"89ab", b"cdef"]
    assert service.blob.ranges == [(0, 4), (4, 4), (8, 4), (12, 4)]
    assert all(length <= 4 for _offset, length in service.blob.ranges)


@pytest.mark.asyncio
async def test_iter_bytes_of_an_empty_blob_yields_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _RangeService(b"")
    monkeypatch.setitem(
        __import__("sys").modules,
        "azure.storage.blob",
        _AZURE_MODULE,
    )
    store, tenant, key = _store(service)
    chunks = [chunk async for chunk in store.iter_bytes(tenant, object_key=key, chunk_size=4)]
    assert chunks == []
    assert service.blob.ranges == []


class _EmptyCopyBlob:
    def __init__(self) -> None:
        self.deleted = False
        self.url = "https://acct.blob.core.windows.net/documents/source"

    def start_copy_from_url(self, url: str) -> None:
        _ = url

    def get_blob_properties(self) -> SimpleNamespace:
        return SimpleNamespace(etag="etag", size=0, version_id=None)

    def delete_blob(self) -> None:
        self.deleted = True


class _EmptyCopyService:
    def __init__(self) -> None:
        self.blob = _EmptyCopyBlob()

    def get_blob_client(self, container: str, blob: str) -> _EmptyCopyBlob:
        _ = container, blob
        return self.blob


@pytest.mark.asyncio
async def test_copy_of_a_zero_byte_blob_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from graph_rag.shared.exceptions import ValidationError

    service = _EmptyCopyService()
    monkeypatch.setitem(
        __import__("sys").modules,
        "azure.storage.blob",
        _AZURE_MODULE,
    )
    store, tenant, source = _store(service)
    dest = source.replace("/staging/", "/original/")
    with pytest.raises(ValidationError, match="empty"):
        await store.copy_object(
            tenant,
            source_key=source,
            dest_key=dest,
            content_type="application/pdf",
            content_hash="ab" * 32,
        )
    assert service.blob.deleted is True
