"""Shared-entity orphan detection for safe graph cleanup."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID

from enterprise_rag.domain.graph.models import GraphNode, GraphRelationship
from enterprise_rag.domain.graph.vocabulary import (
    SemanticNodeLabel,
    SemanticRelationshipType,
    StructuralNodeLabel,
    StructuralRelationshipType,
)

_SHARED_SEMANTIC_LABELS = frozenset(
    {
        SemanticNodeLabel.ENTITY.value,
        SemanticNodeLabel.PERSON.value,
        SemanticNodeLabel.ORGANIZATION.value,
        SemanticNodeLabel.PRODUCT.value,
        SemanticNodeLabel.INGREDIENT.value,
        SemanticNodeLabel.CHEMICAL.value,
        SemanticNodeLabel.REGULATION.value,
        SemanticNodeLabel.LOCATION.value,
        SemanticNodeLabel.CONCEPT.value,
        SemanticNodeLabel.TOPIC.value,
        SemanticNodeLabel.COMMUNITY.value,
    }
)

_VERSION_SCOPED_SEMANTIC = frozenset(
    {
        SemanticNodeLabel.CLAIM.value,
        SemanticNodeLabel.MEASUREMENT.value,
    }
)


def is_shared_semantic_label(label: str) -> bool:
    return label in _SHARED_SEMANTIC_LABELS


def is_version_scoped_semantic_label(label: str) -> bool:
    return label in _VERSION_SCOPED_SEMANTIC


def collect_version_scoped_node_ids(
    nodes: Mapping[UUID, GraphNode],
    relationships: Mapping[UUID, GraphRelationship],
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    chunk_ids: Iterable[UUID] | None = None,
) -> set[UUID]:
    """Identify nodes that belong exclusively to a document version."""
    scoped: set[UUID] = set()
    chunk_id_set = set(chunk_ids or [])

    for node_id, node in nodes.items():
        if node.tenant_id != tenant_id:
            continue
        if node_id == version_id:
            scoped.add(node_id)
            continue
        props = node.properties
        if is_shared_semantic_label(node.label):
            continue
        if props.get("document_id") == str(document_id) and props.get("version_id") == str(
            version_id
        ):
            scoped.add(node_id)
            continue
        if node.label == StructuralNodeLabel.CHUNK.value and (
            node_id in chunk_id_set or props.get("version_id") == str(version_id)
        ):
            scoped.add(node_id)

    scoped_chunks: set[UUID] = set()
    for scoped_id in scoped:
        scoped_node = nodes.get(scoped_id)
        if scoped_node is not None and scoped_node.label == StructuralNodeLabel.CHUNK.value:
            scoped_chunks.add(scoped_id)
    for chunk_id in chunk_id_set:
        chunk_node = nodes.get(chunk_id)
        if chunk_node is not None and chunk_node.label == StructuralNodeLabel.CHUNK.value:
            scoped_chunks.add(chunk_id)
    scoped |= scoped_chunks

    for rel in relationships.values():
        if rel.tenant_id != tenant_id:
            continue
        if rel.relationship_type != StructuralRelationshipType.DERIVED_FROM.value:
            continue
        if rel.target_node_id in scoped_chunks:
            source = nodes.get(rel.source_node_id)
            if source is not None and is_version_scoped_semantic_label(source.label):
                scoped.add(rel.source_node_id)
        if rel.source_node_id in scoped_chunks:
            target = nodes.get(rel.target_node_id)
            if target is not None and is_version_scoped_semantic_label(target.label):
                scoped.add(rel.target_node_id)

    return scoped


def orphan_shared_entity_ids(
    nodes: Mapping[UUID, GraphNode],
    relationships: Mapping[UUID, GraphRelationship],
    *,
    tenant_id: UUID,
    removed_chunk_ids: set[UUID],
    candidate_entity_ids: set[UUID] | None = None,
) -> set[UUID]:
    """Return shared semantic nodes with no remaining MENTIONS after chunk removal."""
    mentioned: dict[UUID, set[UUID]] = {}
    for rel in relationships.values():
        if rel.tenant_id != tenant_id:
            continue
        if rel.relationship_type != SemanticRelationshipType.MENTIONS.value:
            continue
        chunk_id: UUID | None = None
        entity_id: UUID | None = None
        source = nodes.get(rel.source_node_id)
        target = nodes.get(rel.target_node_id)
        if source is not None and source.label == StructuralNodeLabel.CHUNK.value:
            chunk_id = rel.source_node_id
            entity_id = rel.target_node_id
        elif target is not None and target.label == StructuralNodeLabel.CHUNK.value:
            chunk_id = rel.target_node_id
            entity_id = rel.source_node_id
        if chunk_id is None or entity_id is None:
            continue
        if chunk_id in removed_chunk_ids:
            continue
        mentioned.setdefault(entity_id, set()).add(chunk_id)

    candidates = candidate_entity_ids or {
        node_id
        for node_id, node in nodes.items()
        if node.tenant_id == tenant_id and is_shared_semantic_label(node.label)
    }
    orphans: set[UUID] = set()
    for entity_id in candidates:
        node = nodes.get(entity_id)
        if node is None or node.tenant_id != tenant_id:
            continue
        if not is_shared_semantic_label(node.label):
            continue
        if not mentioned.get(entity_id):
            orphans.add(entity_id)
    return orphans


def related_shared_entity_ids(
    relationships: Mapping[UUID, GraphRelationship],
    *,
    tenant_id: UUID,
    chunk_ids: set[UUID],
) -> set[UUID]:
    """Entities/topics mentioned by the given chunks."""
    related: set[UUID] = set()
    for rel in relationships.values():
        if rel.tenant_id != tenant_id:
            continue
        if rel.relationship_type != SemanticRelationshipType.MENTIONS.value:
            continue
        if rel.source_node_id in chunk_ids:
            related.add(rel.target_node_id)
        if rel.target_node_id in chunk_ids:
            related.add(rel.source_node_id)
    return related
