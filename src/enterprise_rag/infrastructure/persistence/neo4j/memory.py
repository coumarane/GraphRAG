"""In-memory graph store for unit tests."""

from __future__ import annotations

import contextlib
from collections import deque
from uuid import UUID

from enterprise_rag.domain.graph.cypher_safety import assert_node_label, assert_relationship_type
from enterprise_rag.domain.graph.models import GraphNode, GraphRelationship, ProjectedGraph
from enterprise_rag.domain.graph.query import (
    GraphClaimHit,
    GraphEntityMatch,
    GraphNeighborHit,
    GraphTopicHit,
)
from enterprise_rag.domain.graph.resolution import normalize_entity_name
from enterprise_rag.domain.graph.vocabulary import (
    SEMANTIC_NODE_LABELS,
    SemanticNodeLabel,
    SemanticRelationshipType,
    StructuralNodeLabel,
    StructuralRelationshipType,
)
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import AuthorizationError

_ENTITY_LABELS = frozenset(
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
    }
)


def _chunk_prop_in(value: object, chunk_ids: set[UUID]) -> bool:
    if not isinstance(value, str):
        return False
    with contextlib.suppress(ValueError):
        return UUID(value) in chunk_ids
    return False


class InMemoryGraphStore:
    """Tenant-isolated graph projection used by unit tests."""

    def __init__(self) -> None:
        self.nodes: dict[UUID, GraphNode] = {}
        self.relationships: dict[UUID, GraphRelationship] = {}

    async def upsert_graph(
        self,
        tenant: TenantContext,
        graph: ProjectedGraph,
    ) -> dict[str, int]:
        if graph.tenant_id != tenant.tenant_id:
            raise AuthorizationError("Graph tenant mismatch")
        node_count = 0
        rel_count = 0
        for node in graph.nodes:
            if node.tenant_id != tenant.tenant_id:
                raise AuthorizationError("Node tenant mismatch")
            assert_node_label(node.label)
            self.nodes[node.node_id] = node
            node_count += 1
        for relationship in graph.relationships:
            if relationship.tenant_id != tenant.tenant_id:
                raise AuthorizationError("Relationship tenant mismatch")
            assert_relationship_type(relationship.relationship_type)
            self.relationships[relationship.relationship_id] = relationship
            rel_count += 1
        return {"nodes": node_count, "relationships": rel_count}

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
        chunk_ids: list[UUID] | None = None,
    ) -> int:
        from enterprise_rag.domain.deletion.orphan import (
            collect_version_scoped_node_ids,
            orphan_shared_entity_ids,
            related_shared_entity_ids,
        )

        scoped = collect_version_scoped_node_ids(
            self.nodes,
            self.relationships,
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            chunk_ids=chunk_ids,
        )
        removed_chunks = {
            node_id
            for node_id in scoped
            if (node := self.nodes.get(node_id)) is not None and node.label == "Chunk"
        }
        if chunk_ids:
            removed_chunks |= set(chunk_ids)

        candidates = related_shared_entity_ids(
            self.relationships,
            tenant_id=tenant.tenant_id,
            chunk_ids=removed_chunks,
        )
        # Drop relationships touching scoped nodes first so orphan detection sees remaining.
        to_delete_rels = [
            rel_id
            for rel_id, rel in self.relationships.items()
            if rel.tenant_id == tenant.tenant_id
            and (
                rel.source_node_id in scoped
                or rel.target_node_id in scoped
                or _chunk_prop_in(rel.properties.get("chunk_id"), removed_chunks)
            )
        ]
        for rel_id in to_delete_rels:
            self.relationships.pop(rel_id, None)

        for node_id in scoped:
            self.nodes.pop(node_id, None)

        orphans = orphan_shared_entity_ids(
            self.nodes,
            self.relationships,
            tenant_id=tenant.tenant_id,
            removed_chunk_ids=removed_chunks,
            candidate_entity_ids=candidates,
        )
        orphan_rels = [
            rel_id
            for rel_id, rel in self.relationships.items()
            if rel.tenant_id == tenant.tenant_id
            and (rel.source_node_id in orphans or rel.target_node_id in orphans)
        ]
        for rel_id in orphan_rels:
            self.relationships.pop(rel_id, None)
        for node_id in orphans:
            self.nodes.pop(node_id, None)

        return len(scoped) + len(orphans) + len(to_delete_rels) + len(orphan_rels)

    async def resolve_entities(
        self,
        tenant: TenantContext,
        *,
        names: list[str],
        limit: int = 20,
    ) -> list[GraphEntityMatch]:
        normalized_names = {normalize_entity_name(name) for name in names if name.strip()}
        if not normalized_names:
            return []
        matches: list[GraphEntityMatch] = []
        for node in self.nodes.values():
            if node.tenant_id != tenant.tenant_id:
                continue
            if node.label not in _ENTITY_LABELS and node.label not in SEMANTIC_NODE_LABELS:
                continue
            if node.label not in _ENTITY_LABELS:
                continue
            node_norm = str(node.properties.get("normalized_name") or "")
            aliases = node.properties.get("aliases")
            alias_norms: set[str] = set()
            if isinstance(aliases, list):
                alias_norms = {
                    normalize_entity_name(str(alias)) for alias in aliases if str(alias).strip()
                }
            canonical = str(node.properties.get("canonical_name") or "")
            canonical_norm = normalize_entity_name(canonical)
            matched = (
                node_norm in normalized_names
                or canonical_norm in normalized_names
                or bool(alias_norms & normalized_names)
                or any(
                    name in node_norm or node_norm in name
                    for name in normalized_names
                    if len(name) >= 4
                )
            )
            if not matched:
                continue
            matches.append(
                GraphEntityMatch(
                    entity_id=node.node_id,
                    canonical_name=str(node.properties.get("canonical_name") or node_norm),
                    normalized_name=node_norm,
                    label=node.label,
                    score=1.0,
                    properties=dict(node.properties),
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def neighborhood(
        self,
        tenant: TenantContext,
        *,
        seed_node_ids: list[UUID],
        depth: int = 2,
        limit: int = 50,
    ) -> list[GraphNeighborHit]:
        if depth < 0:
            return []
        adjacency = self._adjacency(tenant)
        visited: dict[UUID, GraphNeighborHit] = {}
        queue: deque[tuple[UUID, int, str | None]] = deque()
        for seed_id in seed_node_ids:
            node = self.nodes.get(seed_id)
            if node is None or node.tenant_id != tenant.tenant_id:
                continue
            queue.append((seed_id, 0, None))
        while queue and len(visited) < limit:
            node_id, current_depth, via = queue.popleft()
            if node_id in visited:
                continue
            node = self.nodes.get(node_id)
            if node is None or node.tenant_id != tenant.tenant_id:
                continue
            visited[node_id] = GraphNeighborHit(
                node_id=node_id,
                label=node.label,
                depth=current_depth,
                via_relationship=via,
                properties=dict(node.properties),
            )
            if current_depth >= depth:
                continue
            for neighbor_id, rel_type in adjacency.get(node_id, []):
                if neighbor_id not in visited:
                    queue.append((neighbor_id, current_depth + 1, rel_type))
        # Prefer non-seed neighbors first for retrieval usefulness.
        seed_set = set(seed_node_ids)
        ordered = sorted(
            visited.values(),
            key=lambda hit: (0 if hit.node_id in seed_set else 1, hit.depth, str(hit.node_id)),
        )
        return ordered[:limit]

    async def find_claims(
        self,
        tenant: TenantContext,
        *,
        entity_ids: list[UUID] | None = None,
        limit: int = 20,
    ) -> list[GraphClaimHit]:
        related_chunk_ids: set[UUID] = set()
        if entity_ids:
            for rel in self.relationships.values():
                if rel.tenant_id != tenant.tenant_id:
                    continue
                if rel.relationship_type != SemanticRelationshipType.MENTIONS.value:
                    continue
                if rel.target_node_id in entity_ids:
                    related_chunk_ids.add(rel.source_node_id)
                if rel.source_node_id in entity_ids:
                    related_chunk_ids.add(rel.target_node_id)

        claims: list[GraphClaimHit] = []
        for node in self.nodes.values():
            if node.tenant_id != tenant.tenant_id:
                continue
            if node.label != SemanticNodeLabel.CLAIM.value:
                continue
            source_chunk_id = self._claim_source_chunk(tenant, node.node_id)
            if entity_ids and source_chunk_id not in related_chunk_ids:
                # Keep claims whose subject matches an entity canonical name.
                subjects = {
                    str(self.nodes[eid].properties.get("canonical_name") or "").casefold()
                    for eid in entity_ids
                    if eid in self.nodes
                }
                subject = str(node.properties.get("subject") or "").casefold()
                if subject not in subjects:
                    continue
            confidence_raw = node.properties.get("confidence")
            claims.append(
                GraphClaimHit(
                    claim_id=node.node_id,
                    statement=str(node.properties.get("statement") or ""),
                    subject=str(node.properties["subject"])
                    if node.properties.get("subject") is not None
                    else None,
                    predicate=str(node.properties["predicate"])
                    if node.properties.get("predicate") is not None
                    else None,
                    object=str(node.properties["object"])
                    if node.properties.get("object") is not None
                    else None,
                    confidence=(
                        float(confidence_raw)
                        if isinstance(confidence_raw, (int, float))
                        else None
                    ),
                    source_chunk_id=source_chunk_id,
                )
            )
            if len(claims) >= limit:
                break
        return claims

    async def find_topics(
        self,
        tenant: TenantContext,
        *,
        query_terms: list[str],
        limit: int = 20,
    ) -> list[GraphTopicHit]:
        terms = {normalize_entity_name(term) for term in query_terms if term.strip()}
        hits: list[GraphTopicHit] = []
        for node in self.nodes.values():
            if node.tenant_id != tenant.tenant_id:
                continue
            if node.label not in {
                SemanticNodeLabel.TOPIC.value,
                SemanticNodeLabel.COMMUNITY.value,
            }:
                continue
            name = str(node.properties.get("name") or node.properties.get("canonical_name") or "")
            normalized = str(
                node.properties.get("normalized_name") or normalize_entity_name(name)
            )
            score = 0.0
            if not terms:
                score = 0.1
            else:
                for term in terms:
                    if term and (term in normalized or term in normalize_entity_name(name)):
                        score += 1.0
            if score <= 0:
                continue
            hits.append(
                GraphTopicHit(
                    topic_id=node.node_id,
                    name=name or normalized,
                    normalized_name=normalized,
                    label=node.label,
                    score=score,
                    properties=dict(node.properties),
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:limit]

    async def chunk_ids_for_nodes(
        self,
        tenant: TenantContext,
        *,
        node_ids: list[UUID],
        limit: int = 50,
    ) -> list[UUID]:
        wanted = set(node_ids)
        chunk_ids: list[UUID] = []
        seen: set[UUID] = set()

        def _add(chunk_id: UUID) -> None:
            if chunk_id in seen:
                return
            node = self.nodes.get(chunk_id)
            if node is not None and node.label == StructuralNodeLabel.CHUNK.value:
                seen.add(chunk_id)
                chunk_ids.append(chunk_id)

        for node_id in node_ids:
            node = self.nodes.get(node_id)
            if node is not None and node.tenant_id == tenant.tenant_id:
                if node.label == StructuralNodeLabel.CHUNK.value:
                    _add(node_id)
                chunk_prop = node.properties.get("chunk_id")
                if isinstance(chunk_prop, str):
                    with contextlib.suppress(ValueError):
                        _add(UUID(chunk_prop))

        for rel in self.relationships.values():
            if rel.tenant_id != tenant.tenant_id:
                continue
            if rel.relationship_type == SemanticRelationshipType.MENTIONS.value:
                if rel.target_node_id in wanted:
                    _add(rel.source_node_id)
                if rel.source_node_id in wanted:
                    _add(rel.target_node_id)
            if rel.relationship_type == StructuralRelationshipType.DERIVED_FROM.value:
                if rel.source_node_id in wanted:
                    _add(rel.target_node_id)
                if rel.target_node_id in wanted:
                    _add(rel.source_node_id)
            chunk_prop = rel.properties.get("chunk_id")
            if isinstance(chunk_prop, str) and (
                rel.source_node_id in wanted or rel.target_node_id in wanted
            ):
                with contextlib.suppress(ValueError):
                    _add(UUID(chunk_prop))
            if len(chunk_ids) >= limit:
                break
        return chunk_ids[:limit]

    def _adjacency(self, tenant: TenantContext) -> dict[UUID, list[tuple[UUID, str]]]:
        adjacency: dict[UUID, list[tuple[UUID, str]]] = {}
        for rel in self.relationships.values():
            if rel.tenant_id != tenant.tenant_id:
                continue
            adjacency.setdefault(rel.source_node_id, []).append(
                (rel.target_node_id, rel.relationship_type)
            )
            adjacency.setdefault(rel.target_node_id, []).append(
                (rel.source_node_id, rel.relationship_type)
            )
        return adjacency

    def _claim_source_chunk(self, tenant: TenantContext, claim_id: UUID) -> UUID | None:
        for rel in self.relationships.values():
            if rel.tenant_id != tenant.tenant_id:
                continue
            if rel.relationship_type != StructuralRelationshipType.DERIVED_FROM.value:
                continue
            if rel.source_node_id == claim_id:
                return rel.target_node_id
            if rel.target_node_id == claim_id:
                return rel.source_node_id
        return None
