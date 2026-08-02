"""Controlled Neo4j node labels and relationship types.

Labels and predicates used in Cypher must come from these allowlists only.
Unknown LLM predicates map to ``SemanticRelationshipType.RELATES_TO``.
"""

from __future__ import annotations

from enum import StrEnum


class StructuralNodeLabel(StrEnum):
    """Structural document-graph node labels."""

    TENANT = "Tenant"
    DOCUMENT = "Document"
    DOCUMENT_VERSION = "DocumentVersion"
    PAGE = "Page"
    SECTION = "Section"
    CHUNK = "Chunk"
    TEXT_ELEMENT = "TextElement"
    IMAGE = "Image"
    CHART = "Chart"
    DIAGRAM = "Diagram"
    TABLE = "Table"
    TABLE_ROW = "TableRow"
    EQUATION = "Equation"
    CAPTION = "Caption"


class SemanticNodeLabel(StrEnum):
    """Semantic knowledge-graph node labels."""

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
    CLAIM = "Claim"
    MEASUREMENT = "Measurement"
    COMMUNITY = "Community"


class StructuralRelationshipType(StrEnum):
    """Structural graph relationship types."""

    HAS_VERSION = "HAS_VERSION"
    HAS_PAGE = "HAS_PAGE"
    HAS_SECTION = "HAS_SECTION"
    HAS_ELEMENT = "HAS_ELEMENT"
    HAS_CHUNK = "HAS_CHUNK"
    NEXT_ELEMENT = "NEXT_ELEMENT"
    PREVIOUS_ELEMENT = "PREVIOUS_ELEMENT"
    HAS_CAPTION = "HAS_CAPTION"
    APPEARS_ON = "APPEARS_ON"
    DERIVED_FROM = "DERIVED_FROM"
    REFERENCES = "REFERENCES"
    CONTINUES_ON = "CONTINUES_ON"
    HAS_ROW = "HAS_ROW"


class SemanticRelationshipType(StrEnum):
    """Semantic graph relationship types."""

    MENTIONS = "MENTIONS"
    RELATES_TO = "RELATES_TO"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    EXPLAINS = "EXPLAINS"
    ILLUSTRATES = "ILLUSTRATES"
    MEASURES = "MEASURES"
    COMPARES = "COMPARES"
    PRODUCED_BY = "PRODUCED_BY"
    CONTAINS_INGREDIENT = "CONTAINS_INGREDIENT"
    REGULATED_BY = "REGULATED_BY"
    PART_OF = "PART_OF"
    SIMILAR_TO = "SIMILAR_TO"
    MEMBER_OF_COMMUNITY = "MEMBER_OF_COMMUNITY"


NodeLabel = StructuralNodeLabel | SemanticNodeLabel
RelationshipType = StructuralRelationshipType | SemanticRelationshipType

STRUCTURAL_NODE_LABELS: frozenset[str] = frozenset(label.value for label in StructuralNodeLabel)
SEMANTIC_NODE_LABELS: frozenset[str] = frozenset(label.value for label in SemanticNodeLabel)
ALL_NODE_LABELS: frozenset[str] = STRUCTURAL_NODE_LABELS | SEMANTIC_NODE_LABELS

STRUCTURAL_RELATIONSHIP_TYPES: frozenset[str] = frozenset(
    rel.value for rel in StructuralRelationshipType
)
SEMANTIC_RELATIONSHIP_TYPES: frozenset[str] = frozenset(
    rel.value for rel in SemanticRelationshipType
)
ALL_RELATIONSHIP_TYPES: frozenset[str] = STRUCTURAL_RELATIONSHIP_TYPES | SEMANTIC_RELATIONSHIP_TYPES


def normalize_semantic_predicate(proposed: str) -> tuple[SemanticRelationshipType, str | None]:
    """Map an LLM-proposed predicate onto the controlled vocabulary.

    Returns the allowlisted type and the original proposed predicate when it was
    remapped to ``RELATES_TO``.
    """
    normalized = proposed.strip().upper().replace(" ", "_").replace("-", "_")
    try:
        return SemanticRelationshipType(normalized), None
    except ValueError:
        return SemanticRelationshipType.RELATES_TO, proposed
