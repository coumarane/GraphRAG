"""Azurite staging PUT. Production storage account names are refused."""

from __future__ import annotations

import hashlib

import httpx
import pytest

from graph_rag.domain.ids import new_id
from graph_rag.domain.storage.object_keys import staging_object_key
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.azure_blob.object_store import AzureBlobObjectStore
from tests.integration.azurite_support import local_azurite_settings


def test_helper_refuses_production_account_names() -> None:
    with pytest.raises(RuntimeError):
        local_azurite_settings("production")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_presign_put_is_scoped_to_the_staging_key() -> None:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", 10000), timeout=0.4):
            pass
    except OSError:
        pytest.skip("Azurite is not listening on 127.0.0.1:10000")
    store = AzureBlobObjectStore(local_azurite_settings())
    await store.ensure_bucket()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    other = new_id()
    upload_id = new_id()
    staging = staging_object_key(
        tenant_id=tenant.tenant_id, upload_id=upload_id, filename="notes.pdf"
    )
    url = await store.presign_put(tenant, object_key=staging, expires_seconds=900)
    assert staging in url
    assert str(other) not in url
    payload = b"%PDF-1.4\nazurite\n"
    async with httpx.AsyncClient() as client:
        response = await client.put(
            url, content=payload, headers={"x-ms-blob-type": "BlockBlob"}
        )
    assert response.status_code in {200, 201}
    digest = hashlib.sha256()
    total = 0
    async for chunk in store.iter_bytes(tenant, object_key=staging):
        digest.update(chunk)
        total += len(chunk)
    assert total == len(payload)
    assert digest.hexdigest() == hashlib.sha256(payload).hexdigest()
    chunks = [chunk async for chunk in store.iter_bytes(tenant, object_key=staging, chunk_size=4)]
    assert chunks
    assert max(len(chunk) for chunk in chunks) <= 4
    assert b"".join(chunks) == payload
    await store.delete_object(tenant, object_key=staging)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zero_byte_copy_is_rejected_and_not_reported_as_one_byte() -> None:
    import socket

    from graph_rag.domain.storage.object_keys import original_object_key
    from graph_rag.shared.exceptions import NotFoundError, ValidationError

    try:
        with socket.create_connection(("127.0.0.1", 10000), timeout=0.4):
            pass
    except OSError:
        pytest.skip("Azurite is not listening on 127.0.0.1:10000")
    store = AzureBlobObjectStore(local_azurite_settings())
    await store.ensure_bucket()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    upload_id = new_id()
    staging = staging_object_key(
        tenant_id=tenant.tenant_id, upload_id=upload_id, filename="empty.pdf"
    )
    final = original_object_key(
        tenant_id=tenant.tenant_id,
        document_id=new_id(),
        version_id=new_id(),
        filename="empty.pdf",
    )
    url = await store.presign_put(tenant, object_key=staging, expires_seconds=60)
    async with httpx.AsyncClient() as client:
        response = await client.put(url, content=b"", headers={"x-ms-blob-type": "BlockBlob"})
    assert response.status_code in {200, 201}
    head = await store.head_object(tenant, object_key=staging)
    assert head.byte_size == 0
    yielded = [chunk async for chunk in store.iter_bytes(tenant, object_key=staging, chunk_size=8)]
    assert yielded == []
    with pytest.raises(ValidationError, match="empty"):
        await store.copy_object(
            tenant,
            source_key=staging,
            dest_key=final,
            content_type="application/pdf",
            content_hash="ab" * 32,
        )
    with pytest.raises(NotFoundError):
        await store.head_object(tenant, object_key=final)
    await store.delete_object(tenant, object_key=staging)
