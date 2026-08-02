"""In-memory object store for local/dev and unit tests."""

from __future__ import annotations

from enterprise_rag.domain.storage.protocols import StoredObject
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import NotFoundError


class InMemoryObjectStore:
    """Simple tenant-keyed blob map with fake presigned URLs."""

    def __init__(self, *, bucket: str = "enterprise-rag") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}

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
        _ = tenant
        self.objects[object_key] = data
        return StoredObject(
            bucket=self.bucket,
            object_key=object_key,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=len(data),
            etag="inmemory",
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
            del self.objects[key]
        return len(keys)

    async def presign_get(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        expires_seconds: int = 300,
    ) -> str:
        _ = tenant
        if object_key not in self.objects:
            raise NotFoundError("Object not found", details={"object_key": object_key})
        return f"https://objects.local/{object_key}?exp={expires_seconds}"
