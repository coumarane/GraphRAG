"""Knowledge-graph vocabulary and extraction contracts."""

from enterprise_rag.domain.graph.cypher_safety import (
    assert_node_label,
    assert_relationship_type,
    merge_node_cypher,
    merge_relationship_cypher,
    neighborhood_cypher,
)
from enterprise_rag.domain.graph.extraction import (
    EntityType,
    ExtractedClaim,
    ExtractedEntity,
    ExtractedMeasurement,
    ExtractedRelationship,
    GraphExtractionResult,
)
from enterprise_rag.domain.graph.models import (
    EntityResolutionDecision,
    GraphNode,
    GraphRelationship,
    MergeStrategy,
    ProjectedGraph,
    ResolvedEntity,
)
from enterprise_rag.domain.graph.protocols import GraphStore
from enterprise_rag.domain.graph.query import (
    GraphClaimHit,
    GraphEntityMatch,
    GraphNeighborHit,
    GraphPathHint,
    GraphTopicHit,
)
from enterprise_rag.domain.graph.resolution import EntityResolver, normalize_entity_name
from enterprise_rag.domain.graph.structural import StructuralGraphBuilder
from enterprise_rag.domain.graph.vocabulary import (
    ALL_NODE_LABELS,
    ALL_RELATIONSHIP_TYPES,
    SEMANTIC_NODE_LABELS,
    SEMANTIC_RELATIONSHIP_TYPES,
    STRUCTURAL_NODE_LABELS,
    STRUCTURAL_RELATIONSHIP_TYPES,
    NodeLabel,
    RelationshipType,
    SemanticNodeLabel,
    SemanticRelationshipType,
    StructuralNodeLabel,
    StructuralRelationshipType,
    normalize_semantic_predicate,
)

__all__ = [
    "ALL_NODE_LABELS",
    "ALL_RELATIONSHIP_TYPES",
    "SEMANTIC_NODE_LABELS",
    "SEMANTIC_RELATIONSHIP_TYPES",
    "STRUCTURAL_NODE_LABELS",
    "STRUCTURAL_RELATIONSHIP_TYPES",
    "EntityResolutionDecision",
    "EntityResolver",
    "EntityType",
    "ExtractedClaim",
    "ExtractedEntity",
    "ExtractedMeasurement",
    "ExtractedRelationship",
    "GraphClaimHit",
    "GraphEntityMatch",
    "GraphExtractionResult",
    "GraphNeighborHit",
    "GraphNode",
    "GraphPathHint",
    "GraphRelationship",
    "GraphStore",
    "GraphTopicHit",
    "MergeStrategy",
    "NodeLabel",
    "ProjectedGraph",
    "RelationshipType",
    "ResolvedEntity",
    "SemanticNodeLabel",
    "SemanticRelationshipType",
    "StructuralGraphBuilder",
    "StructuralNodeLabel",
    "StructuralRelationshipType",
    "assert_node_label",
    "assert_relationship_type",
    "merge_node_cypher",
    "merge_relationship_cypher",
    "neighborhood_cypher",
    "normalize_entity_name",
    "normalize_semantic_predicate",
]
