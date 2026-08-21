"""In-memory chunk lookup store for retrieval expansion."""

from __future__ import annotations

from uuid import UUID

from enterprise_rag.domain.chunks.models import ChunkBase
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import AuthorizationError


class InMemoryChunkLookupStore:
    """Tenant-isolated chunk SoR stand-in for unit tests."""

    def __init__(self) -> None:
        self._chunks: dict[UUID, ChunkBase] = {}

    async def upsert(self, tenant: TenantContext, chunks: list[ChunkBase]) -> int:
        written = 0
        for chunk in chunks:
            if chunk.tenant_id != tenant.tenant_id:
                raise AuthorizationError("Chunk tenant mismatch")
            self._chunks[chunk.chunk_id] = chunk
            written += 1
        return written

    async def get_chunks(
        self,
        tenant: TenantContext,
        chunk_ids: list[UUID],
    ) -> list[ChunkBase]:
        found: list[ChunkBase] = []
        for chunk_id in chunk_ids:
            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                continue
            if chunk.tenant_id != tenant.tenant_id:
                raise AuthorizationError("Chunk tenant mismatch on lookup")
            found.append(chunk)
        return found

    def as_map(self, tenant: TenantContext) -> dict[UUID, ChunkBase]:
        return {
            chunk_id: chunk
            for chunk_id, chunk in self._chunks.items()
            if chunk.tenant_id == tenant.tenant_id
        }

    def list_for_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> list[ChunkBase]:
        return [
            chunk
            for chunk in self._chunks.values()
            if chunk.tenant_id == tenant.tenant_id
            and chunk.document_id == document_id
            and chunk.version_id == version_id
        ]

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> int:
        to_delete = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if chunk.tenant_id == tenant.tenant_id
            and chunk.document_id == document_id
            and chunk.version_id == version_id
        ]
        for chunk_id in to_delete:
            del self._chunks[chunk_id]
        return len(to_delete)
