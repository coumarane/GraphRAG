"""In-memory object store for local/dev and unit tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

from graph_rag.domain.storage.object_keys import assert_tenant_object_prefix
from graph_rag.domain.storage.protocols import ObjectHead, StoredObject
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import NotFoundError, ValidationError


class InMemoryObjectStore:
    """Simple tenant-keyed blob map with fake presigned URLs."""

    def __init__(self, *, bucket: str = "enterprise-rag") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}
        self.versions: dict[str, str | None] = {}
        self.content_types: dict[str, str] = {}
        self.hashes: dict[str, str] = {}
        self.locked: set[str] = set()

    async def ensure_bucket(self) -> None:
        return None

    def _reject_locked(self, object_key: str) -> None:
        if object_key in self.locked:
            raise ValidationError(
                "Accepted object cannot be modified",
                details={"object_key": object_key},
            )

    def _put_expiry(self, expires_seconds: int) -> None:
        if expires_seconds < 1 or expires_seconds > 900:
            raise ValidationError(
                "Write URL expiry must be between 1 and 900 seconds",
                details={"expires_seconds": expires_seconds},
            )

    async def put_bytes(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        content_hash: str,
    ) -> StoredObject:
        _ = tenant
        self._reject_locked(object_key)
        self.objects[object_key] = data
        self.content_types[object_key] = content_type
        self.hashes[object_key] = content_hash
        etag = f"mem-{content_hash[:16]}-{len(data)}"
        self.etags[object_key] = etag
        return StoredObject(
            bucket=self.bucket,
            object_key=object_key,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=len(data),
            etag=etag,
        )

    async def get_bytes(self, tenant: TenantContext, *, object_key: str) -> bytes:
        _ = tenant
        if object_key not in self.objects:
            raise NotFoundError("Object not found", details={"object_key": object_key})
        return self.objects[object_key]

    async def delete_prefix(self, tenant: TenantContext, *, prefix: str) -> int:
        _ = tenant
        keys = [key for key in self.objects if key.startswith(prefix)]
        for key in keys:
            self._drop(key)
        return len(keys)

    def _drop(self, object_key: str) -> None:
        self.objects.pop(object_key, None)
        self.etags.pop(object_key, None)
        self.versions.pop(object_key, None)
        self.content_types.pop(object_key, None)
        self.hashes.pop(object_key, None)
        self.locked.discard(object_key)

    async def presign_get(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        expires_seconds: int = 300,
    ) -> str:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)
        if object_key not in self.objects:
            raise NotFoundError("Object not found", details={"object_key": object_key})
        return f"https://objects.local/{object_key}?exp={expires_seconds}"

    async def presign_put(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        expires_seconds: int = 900,
    ) -> str:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)
        self._put_expiry(expires_seconds)
        if "/uploads/" not in object_key or "/staging/" not in object_key:
            raise ValidationError(
                "Write URL can name only a staging key",
                details={"object_key": object_key},
            )
        return f"https://objects.local/{object_key}?exp={expires_seconds}&method=PUT"

    async def iter_bytes(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        data = await self.get_bytes(tenant, object_key=object_key)
        for index in range(0, len(data), chunk_size):
            yield data[index : index + chunk_size]

    async def copy_object(
        self,
        tenant: TenantContext,
        *,
        source_key: str,
        dest_key: str,
        content_type: str,
        content_hash: str,
    ) -> StoredObject:
        data = await self.get_bytes(tenant, object_key=source_key)
        return await self.put_bytes(
            tenant,
            object_key=dest_key,
            data=data,
            content_type=content_type,
            content_hash=content_hash,
        )

    async def delete_object(self, tenant: TenantContext, *, object_key: str) -> None:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)
        self._drop(object_key)

    async def head_object(self, tenant: TenantContext, *, object_key: str) -> ObjectHead:
        data = await self.get_bytes(tenant, object_key=object_key)
        return ObjectHead(
            object_key=object_key,
            byte_size=len(data),
            etag=self.etags.get(object_key),
            version_id=self.versions.get(object_key),
        )

    async def lock_object(self, tenant: TenantContext, *, object_key: str) -> None:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)
        if object_key not in self.objects:
            raise NotFoundError("Object not found", details={"object_key": object_key})
        self.locked.add(object_key)
