"""Cypher safety helpers — labels/types from allowlists only."""

from __future__ import annotations

from collections.abc import Mapping

from enterprise_rag.domain.graph.vocabulary import (
    ALL_NODE_LABELS,
    ALL_RELATIONSHIP_TYPES,
)
from enterprise_rag.shared.exceptions import GraphError, ValidationError


def assert_node_label(label: str) -> str:
    if label not in ALL_NODE_LABELS:
        raise ValidationError(
            "Node label is not allowlisted",
            details={"label": label},
        )
    return label


def assert_relationship_type(relationship_type: str) -> str:
    if relationship_type not in ALL_RELATIONSHIP_TYPES:
        raise ValidationError(
            "Relationship type is not allowlisted",
            details={"relationship_type": relationship_type},
        )
    return relationship_type


def merge_node_cypher(label: str) -> str:
    """Return a parameterized MERGE template for an allowlisted label."""
    safe = assert_node_label(label)
    # Label interpolated only after allowlist check; properties stay parameterized.
    return (
        f"MERGE (n:{safe} {{node_id: $node_id, tenant_id: $tenant_id}}) "
        "SET n += $properties "
        "RETURN n.node_id AS node_id"
    )


def merge_relationship_cypher(relationship_type: str) -> str:
    """Return a parameterized MERGE template for an allowlisted relationship."""
    safe = assert_relationship_type(relationship_type)
    return (
        "MATCH (a {node_id: $source_node_id, tenant_id: $tenant_id}) "
        "MATCH (b {node_id: $target_node_id, tenant_id: $tenant_id}) "
        f"MERGE (a)-[r:{safe} {{relationship_id: $relationship_id}}]->(b) "
        "SET r += $properties "
        "RETURN r.relationship_id AS relationship_id"
    )


def require_tenant_param(params: Mapping[str, object]) -> None:
    if "tenant_id" not in params:
        raise GraphError("Cypher parameters must include tenant_id")


def neighborhood_cypher(*, depth: int) -> str:
    """Bounded undirected neighborhood template; depth is validated then interpolated."""
    if depth < 0 or depth > 10:
        raise ValidationError(
            "Graph neighborhood depth out of bounds",
            details={"depth": depth, "min": 0, "max": 10},
        )
    if depth == 0:
        return (
            "MATCH (seed {tenant_id: $tenant_id}) "
            "WHERE seed.node_id IN $seed_ids "
            "RETURN seed.node_id AS node_id, seed.label AS label, 0 AS depth, "
            "null AS via_relationship, properties(seed) AS properties "
            "LIMIT $limit"
        )
    return (
        "MATCH (seed {tenant_id: $tenant_id}) "
        "WHERE seed.node_id IN $seed_ids "
        f"MATCH path = (seed)-[*1..{depth}]-(neighbor) "
        "WHERE neighbor.tenant_id = $tenant_id "
        "WITH neighbor, length(path) AS depth, relationships(path)[-1] AS last_rel "
        "RETURN DISTINCT neighbor.node_id AS node_id, neighbor.label AS label, depth, "
        "type(last_rel) AS via_relationship, properties(neighbor) AS properties "
        "ORDER BY depth ASC "
        "LIMIT $limit"
    )
