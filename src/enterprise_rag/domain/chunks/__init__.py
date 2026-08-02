"""Chunk domain types."""

from enterprise_rag.domain.chunks.models import ChunkBase, ChunkType
from enterprise_rag.domain.chunks.protocols import ChunkVectorStore
from enterprise_rag.domain.chunks.vectors import (
    ChunkingResult,
    ChunkVectorPayload,
    ChunkVectorRecord,
    VectorSearchHit,
    VectorSearchRequest,
)

__all__ = [
    "ChunkBase",
    "ChunkType",
    "ChunkVectorPayload",
    "ChunkVectorRecord",
    "ChunkVectorStore",
    "ChunkingResult",
    "VectorSearchHit",
    "VectorSearchRequest",
]
