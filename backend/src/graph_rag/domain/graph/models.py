"""In-memory graph projection models prior to Neo4j upsert."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.graph.vocabulary import NodeLabel, RelationshipType
from graph_rag.domain.types import JsonValue


class MergeStrategy(StrEnum):
    """How a mention was linked to a canonical entity."""

    EXACT_NORMALIZED = "exact_normalized"
    EXACT_ALIAS = "exact_alias"
    ACRONYM = "acronym"
    EXACT_IDENTIFIER = "exact_identifier"
    FUZZY_AND_TYPE = "fuzzy_and_type"
    EMBEDDING_AND_TYPE = "embedding_and_type"
    NEW_ENTITY = "new_entity"


class GraphNode(BaseModel):
    """Allowlisted graph node awaiting projection."""

    model_config = ConfigDict(extra="forbid")

    node_id: UUID
    label: str
    tenant_id: UUID
    properties: dict[str, JsonValue] = Field(default_factory=dict)

    def validated_label(self, allowlist: frozenset[str]) -> str:
        if self.label not in allowlist:
            msg = f"Node label '{self.label}' is not allowlisted"
            raise ValueError(msg)
        return self.label


class GraphRelationship(BaseModel):
    """Allowlisted graph relationship awaiting projection."""

    model_config = ConfigDict(extra="forbid")

    relationship_id: UUID
    relationship_type: str
    tenant_id: UUID
    source_node_id: UUID
    target_node_id: UUID
    properties: dict[str, JsonValue] = Field(default_factory=dict)

    def validated_type(self, allowlist: frozenset[str]) -> str:
        if self.relationship_type not in allowlist:
            msg = f"Relationship type '{self.relationship_type}' is not allowlisted"
            raise ValueError(msg)
        return self.relationship_type


class ProjectedGraph(BaseModel):
    """Tenant-scoped structural + semantic graph projection."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    nodes: list[GraphNode] = Field(default_factory=list)
    relationships: list[GraphRelationship] = Field(default_factory=list)


class ResolvedEntity(BaseModel):
    """Canonical tenant-scoped entity after resolution."""

    model_config = ConfigDict(extra="forbid")

    entity_id: UUID
    tenant_id: UUID
    canonical_name: str
    normalized_name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    mention_count: int = Field(default=1, ge=1)
    source_element_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class EntityResolutionDecision(BaseModel):
    """Audit trail for a single mention resolution."""

    model_config = ConfigDict(extra="forbid")

    mention_name: str
    canonical_entity_id: UUID
    merge_strategy: MergeStrategy
    confidence: float = Field(ge=0.0, le=1.0)
    requires_manual_review: bool = False
    signals: dict[str, JsonValue] = Field(default_factory=dict)


# Re-export typing helpers used by builders.
NodeLabelType = NodeLabel
RelationshipTypeAlias = RelationshipType
