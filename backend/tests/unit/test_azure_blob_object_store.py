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


@pytest.mark.asyncio
async def test_put_bytes_uses_azure_safe_metadata_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_service = _FakeBlobServiceClient()

    class _ImportedBlobServiceClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

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
        content_hash="ABC123",
    )

    assert fake_service.last_container == "documents"
    assert fake_service.last_blob == object_key
    assert fake_service.blob_client.calls == [
        {
            "data": b"pdf-bytes",
            "overwrite": True,
            "content_type": "application/pdf",
            "metadata": {
                "content_sha256": "ABC123",
                "tenant_id": str(tenant.tenant_id),
            },
        }
    ]
    assert stored.etag == "azure-etag"
    assert stored.content_hash == "abc123"
