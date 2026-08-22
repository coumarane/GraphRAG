"""Vector store protocol for chunk embeddings."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from graph_rag.domain.chunks.vectors import (
    ChunkVectorRecord,
    VectorSearchHit,
    VectorSearchRequest,
)
from graph_rag.domain.tenant import TenantContext


class ChunkVectorStore(Protocol):
    """Tenant-aware chunk vector index (Qdrant adapter)."""

    async def ensure_collection(self, *, vector_size: int) -> None:
        """Create the chunks collection when missing."""
        ...

    async def upsert(
        self,
        tenant: TenantContext,
        records: list[ChunkVectorRecord],
    ) -> int:
        """Upsert embedded chunks. Returns written point count."""
        ...

    async def search(
        self,
        tenant: TenantContext,
        request: VectorSearchRequest,
    ) -> list[VectorSearchHit]:
        """Search child/parent chunks with mandatory tenant filtering."""
        ...

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> int:
        """Delete all points for a document version. Returns deleted count."""
        ...

    async def delete_document(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
    ) -> int:
        """Delete all points for a document across versions. Returns deleted count."""
        ...
