"""Graph vocabulary and extraction tests."""

from __future__ import annotations

from graph_rag.domain.graph import (
    ALL_NODE_LABELS,
    ALL_RELATIONSHIP_TYPES,
    ExtractedRelationship,
    SemanticRelationshipType,
    StructuralNodeLabel,
    normalize_semantic_predicate,
)


def test_allowlists_include_structural_and_semantic() -> None:
    assert StructuralNodeLabel.DOCUMENT.value in ALL_NODE_LABELS
    assert "Claim" in ALL_NODE_LABELS
    assert "HAS_VERSION" in ALL_RELATIONSHIP_TYPES
    assert "REGULATED_BY" in ALL_RELATIONSHIP_TYPES


def test_unknown_predicate_maps_to_relates_to() -> None:
    predicate, original = normalize_semantic_predicate("caused-by-somehow")
    assert predicate is SemanticRelationshipType.RELATES_TO
    assert original == "caused-by-somehow"


def test_known_predicate_preserved() -> None:
    predicate, original = normalize_semantic_predicate("supports")
    assert predicate is SemanticRelationshipType.SUPPORTS
    assert original is None


def test_extracted_relationship_remaps_unknown_predicate() -> None:
    rel = ExtractedRelationship(
        source_entity="A",
        target_entity="B",
        predicate="invented_edge",
        confidence=0.5,
    )
    assert rel.predicate is SemanticRelationshipType.RELATES_TO
    assert rel.proposed_predicate == "invented_edge"
