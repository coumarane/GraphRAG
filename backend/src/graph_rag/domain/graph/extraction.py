"""Structured extraction schemas for graph construction."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from graph_rag.domain.graph.vocabulary import (
    SemanticNodeLabel,
    SemanticRelationshipType,
    normalize_semantic_predicate,
)


class EntityType(StrEnum):
    """Entity kinds aligned with semantic node labels (excluding Claim/Measurement)."""

    ENTITY = "Entity"
    PERSON = "Person"
    ORGANIZATION = "Organization"
    PRODUCT = "Product"
    INGREDIENT = "Ingredient"
    CHEMICAL = "Chemical"
    REGULATION = "Regulation"
    LOCATION = "Location"
    CONCEPT = "Concept"
    TOPIC = "Topic"

    def to_node_label(self) -> SemanticNodeLabel:
        return SemanticNodeLabel(self.value)


class ExtractedEntity(BaseModel):
    """Entity mention extracted from a parent or composite chunk."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    entity_type: EntityType
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    source_element_ids: list[UUID] = Field(default_factory=list)


class ExtractedRelationship(BaseModel):
    """Relationship between extracted entities."""

    model_config = ConfigDict(extra="forbid")

    source_entity: str = Field(min_length=1)
    target_entity: str = Field(min_length=1)
    predicate: SemanticRelationshipType = SemanticRelationshipType.RELATES_TO
    proposed_predicate: str | None = None
    description: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_element_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_predicate(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        predicate = data.get("predicate")
        if not isinstance(predicate, str):
            return data
        mapped, original = normalize_semantic_predicate(predicate)
        updated = dict(data)
        updated["predicate"] = mapped
        if original is not None:
            updated.setdefault("proposed_predicate", original)
        return updated


class ExtractedClaim(BaseModel):
    """Factual claim grounded in source elements."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_element_ids: list[UUID] = Field(default_factory=list)


class ExtractedMeasurement(BaseModel):
    """Numeric or qualitative measurement with optional unit."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    unit: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_element_ids: list[UUID] = Field(default_factory=list)


class GraphExtractionResult(BaseModel):
    """Bundle of structured extraction outputs for one chunk region."""

    model_config = ConfigDict(extra="forbid")

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    measurements: list[ExtractedMeasurement] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
