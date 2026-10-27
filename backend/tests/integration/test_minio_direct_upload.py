"""Direct staging upload against local Compose MinIO."""

from __future__ import annotations

import contextlib
import hashlib

import httpx
import pytest

from graph_rag.config.settings import MinioSettings
from graph_rag.domain.ids import new_id
from graph_rag.domain.storage.object_keys import staging_object_key
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.minio.object_store import MinioObjectStore


@pytest.mark.integration
@pytest.mark.asyncio
async def test_staging_put_does_not_replace_final_object(compose_minio: None) -> None:
    _ = compose_minio
    store = MinioObjectStore(MinioSettings())
    await store.ensure_bucket()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    upload_id = new_id()
    staging = staging_object_key(
        tenant_id=tenant.tenant_id, upload_id=upload_id, filename="notes.pdf"
    )
    final = f"tenants/{tenant.tenant_id}/documents/{new_id()}/original/notes.pdf"
    payload = b"%PDF-1.4\nnotes\n"
    url = await store.presign_put(tenant, object_key=staging, expires_seconds=900)
    assert "/uploads/" in url and "/staging/" in url
    async with httpx.AsyncClient() as client:
        response = await client.put(url, content=payload)
    assert response.status_code in {200, 204}
    copied = await store.copy_object(
        tenant,
        source_key=staging,
        dest_key=final,
        content_type="application/pdf",
        content_hash=hashlib.sha256(payload).hexdigest(),
    )
    await store.lock_object(tenant, object_key=final)
    await store.delete_object(tenant, object_key=staging)
    replacement = b"%PDF-1.4\nchanged\n"
    async with httpx.AsyncClient() as client:
        again = await client.put(url, content=replacement)
    assert again.status_code in {200, 204, 403}
    head = await store.head_object(tenant, object_key=final)
    assert head.byte_size == len(payload)
    assert head.etag == copied.etag
    await store.delete_object(tenant, object_key=staging)
    with contextlib.suppress(Exception):
        await store.delete_object(tenant, object_key=final)
