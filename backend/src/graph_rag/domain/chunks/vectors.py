"""Vector indexing contracts for chunk embeddings."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.chunks.models import ChunkBase, ChunkType
from graph_rag.domain.modality import Modality
from graph_rag.domain.types import JsonValue


class ChunkVectorPayload(BaseModel):
    """Qdrant payload fields required for tenant-safe retrieval."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    chunk_id: UUID
    parent_chunk_id: UUID | None = None
    modality: Modality
    chunk_type: ChunkType
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    section_path: list[str] = Field(default_factory=list)
    content_hash: str = Field(min_length=64, max_length=64)
    source_object_keys: list[str] = Field(default_factory=list)
    text_preview: str = ""
    language: str | None = None
    parser: str | None = None
    security_labels: list[str] = Field(default_factory=list)
    department: str | None = None
    country: str | None = None
    business_unit: str | None = None
    classification: str | None = None
    required_clearance: int | None = None
    allowed_groups: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ChunkVectorRecord(BaseModel):
    """Embedded chunk ready for upsert into a vector store."""

    model_config = ConfigDict(extra="forbid")

    point_id: UUID
    content_vector: list[float] = Field(min_length=1)
    summary_vector: list[float] | None = None
    payload: ChunkVectorPayload


class VectorSearchHit(BaseModel):
    """Single vector search result."""

    model_config = ConfigDict(extra="forbid")

    point_id: UUID
    score: float
    payload: ChunkVectorPayload
    chunk: ChunkBase | None = None


class VectorSearchRequest(BaseModel):
    """Tenant-scoped dense retrieval request."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    query_vector: list[float] = Field(min_length=1)
    top_k: int = Field(default=12, ge=1, le=100)
    document_ids: list[UUID] = Field(default_factory=list)
    modalities: list[Modality] = Field(default_factory=list)
    vector_name: str = "content"
    # ABAC / security payload filters (subject-derived; never from client alone).
    max_clearance: int | None = None
    countries: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    security_labels: list[str] = Field(default_factory=list)


class ChunkingResult(BaseModel):
    """Output of hierarchical multimodal chunking."""

    model_config = ConfigDict(extra="forbid")

    parents: list[ChunkBase] = Field(default_factory=list)
    children: list[ChunkBase] = Field(default_factory=list)

    @property
    def all_chunks(self) -> list[ChunkBase]:
        return [*self.parents, *self.children]
