"""Lexical store that hydrates from durable Qdrant chunk payloads on first use."""

from __future__ import annotations

from uuid import UUID

from enterprise_rag.domain.chunks.models import ChunkBase
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.retrieval.protocols import LexicalHit
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.persistence.chunks.lexical_memory import (
    InMemoryLexicalSearchStore,
)
from enterprise_rag.infrastructure.persistence.chunks.qdrant_lookup import (
    QdrantChunkLookupStore,
)


class QdrantHydratingLexicalStore:
    """Wrap in-memory BM25 with one-shot Qdrant payload hydration per tenant."""

    def __init__(
        self,
        chunk_store: QdrantChunkLookupStore,
        *,
        inner: InMemoryLexicalSearchStore | None = None,
    ) -> None:
        self._chunks = chunk_store
        self._inner = inner or InMemoryLexicalSearchStore()
        self._hydrated: set[UUID] = set()

    async def _ensure_hydrated(self, tenant: TenantContext) -> None:
        if tenant.tenant_id in self._hydrated:
            return
        self._chunks.hydrate_from_qdrant(tenant)
        cached = list(self._chunks.as_map(tenant).values())
        if cached:
            await self._inner.upsert(tenant, cached)
        self._hydrated.add(tenant.tenant_id)

    async def upsert(self, tenant: TenantContext, chunks: list[ChunkBase]) -> int:
        written = await self._inner.upsert(tenant, chunks)
        self._hydrated.add(tenant.tenant_id)
        return written

    async def search(
        self,
        tenant: TenantContext,
        *,
        query: str,
        top_k: int = 12,
        document_ids: list[UUID] | None = None,
        modalities: list[Modality] | None = None,
    ) -> list[LexicalHit]:
        await self._ensure_hydrated(tenant)
        return await self._inner.search(
            tenant,
            query=query,
            top_k=top_k,
            document_ids=document_ids,
            modalities=modalities,
        )

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> int:
        return await self._inner.delete_version(
            tenant,
            document_id=document_id,
            version_id=version_id,
        )
