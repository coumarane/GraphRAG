"""Retrieval-side storage protocols (chunk lookup and lexical search)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.chunks.models import ChunkBase
from graph_rag.domain.modality import Modality
from graph_rag.domain.tenant import TenantContext


class LexicalHit(BaseModel):
    """Sparse / full-text style search hit."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    score: float = Field(ge=0.0)


class ChunkLookupStore(Protocol):
    """Hydrate full chunk records for expansion and evidence assembly."""

    async def get_chunks(
        self,
        tenant: TenantContext,
        chunk_ids: list[UUID],
    ) -> list[ChunkBase]:
        """Return chunks owned by the tenant; missing IDs are omitted."""
        ...

    async def upsert(
        self,
        tenant: TenantContext,
        chunks: list[ChunkBase],
    ) -> int:
        """Upsert chunks for later lookup. Returns written count."""
        ...

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> int:
        """Remove chunks for a document version. Returns deleted count."""
        ...


class LexicalSearchStore(Protocol):
    """Sparse / full-text style chunk search."""

    async def search(
        self,
        tenant: TenantContext,
        *,
        query: str,
        top_k: int = 12,
        document_ids: list[UUID] | None = None,
        modalities: list[Modality] | None = None,
    ) -> list[LexicalHit]:
        """Return ranked lexical hits for the tenant."""
        ...

    async def upsert(
        self,
        tenant: TenantContext,
        chunks: list[ChunkBase],
    ) -> int:
        """Index chunk text for lexical search."""
        ...

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> int:
        """Remove lexical entries for a document version. Returns deleted count."""
        ...
