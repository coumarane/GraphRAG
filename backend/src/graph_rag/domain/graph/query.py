"""Graph query result contracts used by local/global retrieval."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.types import JsonValue


class GraphEntityMatch(BaseModel):
    """Entity resolved from a query mention."""

    model_config = ConfigDict(extra="forbid")

    entity_id: UUID
    canonical_name: str
    normalized_name: str
    label: str
    score: float = 1.0
    properties: dict[str, JsonValue] = Field(default_factory=dict)


class GraphNeighborHit(BaseModel):
    """Node reached within a bounded neighborhood traversal."""

    model_config = ConfigDict(extra="forbid")

    node_id: UUID
    label: str
    depth: int = Field(ge=0)
    via_relationship: str | None = None
    properties: dict[str, JsonValue] = Field(default_factory=dict)


class GraphClaimHit(BaseModel):
    """Claim linked to query entities or neighborhoods."""

    model_config = ConfigDict(extra="forbid")

    claim_id: UUID
    statement: str
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    confidence: float | None = None
    source_chunk_id: UUID | None = None


class GraphTopicHit(BaseModel):
    """Topic or community summary candidate for global retrieval."""

    model_config = ConfigDict(extra="forbid")

    topic_id: UUID
    name: str
    normalized_name: str
    label: str = "Topic"
    score: float = 1.0
    properties: dict[str, JsonValue] = Field(default_factory=dict)


class GraphPathHint(BaseModel):
    """Lightweight path description assembled during graph retrieval."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    chunk_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
