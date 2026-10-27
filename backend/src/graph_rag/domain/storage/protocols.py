"""Object store and source intake protocols."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.tenant import TenantContext


class ObjectHead(BaseModel):
    """Size and identity of a stored object. Bytes are not included."""

    model_config = ConfigDict(extra="forbid")

    object_key: str
    byte_size: int = Field(ge=0)
    etag: str | None = None
    version_id: str | None = None


class StoredObject(BaseModel):
    """Metadata for an object written to blob storage."""

    model_config = ConfigDict(extra="forbid")

    bucket: str
    object_key: str
    content_type: str
    content_hash: str = Field(min_length=64, max_length=64)
    byte_size: int = Field(ge=1)
    etag: str | None = None


class ObjectStore(Protocol):
    """Tenant-aware object storage port (MinIO adapter)."""

    async def ensure_bucket(self) -> None:
        """Create the configured bucket when missing."""
        ...

    async def put_bytes(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        content_hash: str,
    ) -> StoredObject:
        """Store bytes under a tenant-prefixed object key."""
        ...

    async def get_bytes(self, tenant: TenantContext, *, object_key: str) -> bytes:
        """Read object bytes after tenant ownership validation."""
        ...

    async def delete_prefix(self, tenant: TenantContext, *, prefix: str) -> int:
        """Delete all objects under a tenant-owned prefix. Returns deleted count."""
        ...

    async def presign_get(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        expires_seconds: int = 300,
    ) -> str:
        """Create a short-lived GET URL for an owned object."""
        ...

    async def presign_put(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        expires_seconds: int = 900,
    ) -> str:
        """Create a short-lived PUT URL for one staging key. Expiry is 1-900 seconds."""
        ...

    def iter_bytes(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        """Stream an owned object without returning it as one buffer."""
        ...

    async def copy_object(
        self,
        tenant: TenantContext,
        *,
        source_key: str,
        dest_key: str,
        content_type: str,
        content_hash: str,
    ) -> StoredObject:
        """Copy bytes to a final key the write URL cannot name."""
        ...

    async def delete_object(self, tenant: TenantContext, *, object_key: str) -> None:
        """Delete one owned object."""
        ...

    async def head_object(self, tenant: TenantContext, *, object_key: str) -> ObjectHead:
        """Return size and etag for an owned object."""
        ...

    async def lock_object(self, tenant: TenantContext, *, object_key: str) -> None:
        """Apply retention when the backend supports it. The protected key remains mandatory."""
        ...


class SourceBytes(BaseModel):
    """Validated source payload ready for hashing/storage."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    filename: str
    mime_type: str
    content: bytes
    source_uri: str | None = None


class SourceLoader(Protocol):
    """Load local files or remote URLs into validated bytes."""

    async def load_local(self, path: str) -> SourceBytes:
        """Read and validate a local filesystem path."""
        ...

    async def load_url(self, url: str) -> SourceBytes:
        """Safely download and validate a remote URL."""
        ...


class HashingService(Protocol):
    """Content hashing port."""

    def sha256_hex(self, data: bytes) -> str:
        """Return lowercase SHA-256 hex digest."""
        ...


async def iter_chunks(data: bytes, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
    """Yield fixed-size chunks (helper for streaming adapters)."""
    for index in range(0, len(data), chunk_size):
        yield data[index : index + chunk_size]


def version_prefix(*, tenant_id: UUID, document_id: UUID, version_id: UUID) -> str:
    return f"tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/"
