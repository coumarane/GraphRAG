"""Neo4j graph projection adapter."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from enterprise_rag.config.settings import Neo4jSettings
from enterprise_rag.domain.graph.cypher_safety import (
    merge_node_cypher,
    merge_relationship_cypher,
    neighborhood_cypher,
    require_tenant_param,
)
from enterprise_rag.domain.graph.models import ProjectedGraph
from enterprise_rag.domain.graph.query import (
    GraphClaimHit,
    GraphEntityMatch,
    GraphNeighborHit,
    GraphTopicHit,
)
from enterprise_rag.domain.graph.resolution import normalize_entity_name
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import AuthorizationError, ConfigurationError, StorageError


class Neo4jGraphStore:
    """Project allowlisted graphs with parameterized Cypher only."""

    def __init__(
        self,
        settings: Neo4jSettings | None = None,
        *,
        driver: Any | None = None,
    ) -> None:
        self._settings = settings or Neo4jSettings()
        self._driver = driver

    def _get_driver(self) -> Any:
        if self._driver is not None:
            return self._driver
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise ConfigurationError(
                "Optional dependency 'neo4j' is not installed",
                details={"extra": "neo4j", "module": "neo4j"},
                cause=exc,
            ) from exc
        self._driver = GraphDatabase.driver(
            self._settings.uri,
            auth=(self._settings.user, self._settings.password.get_secret_value()),
        )
        return self._driver

    async def upsert_graph(
        self,
        tenant: TenantContext,
        graph: ProjectedGraph,
    ) -> dict[str, int]:
        if graph.tenant_id != tenant.tenant_id:
            raise AuthorizationError("Graph tenant mismatch")
        driver = self._get_driver()
        node_count = 0
        rel_count = 0
        try:
            with driver.session() as session:
                for node in graph.nodes:
                    if node.tenant_id != tenant.tenant_id:
                        raise AuthorizationError("Node tenant mismatch")
                    query = merge_node_cypher(node.label)
                    params = {
                        "node_id": str(node.node_id),
                        "tenant_id": str(tenant.tenant_id),
                        "properties": {
                            **{key: _jsonable(value) for key, value in node.properties.items()},
                            "label": node.label,
                        },
                    }
                    require_tenant_param(params)
                    session.run(query, params)
                    node_count += 1
                for relationship in graph.relationships:
                    if relationship.tenant_id != tenant.tenant_id:
                        raise AuthorizationError("Relationship tenant mismatch")
                    query = merge_relationship_cypher(relationship.relationship_type)
                    params = {
                        "relationship_id": str(relationship.relationship_id),
                        "tenant_id": str(tenant.tenant_id),
                        "source_node_id": str(relationship.source_node_id),
                        "target_node_id": str(relationship.target_node_id),
                        "properties": {
                            key: _jsonable(value)
                            for key, value in relationship.properties.items()
                        },
                    }
                    require_tenant_param(params)
                    session.run(query, params)
                    rel_count += 1
        except (AuthorizationError, ConfigurationError):
            raise
        except Exception as exc:
            raise StorageError("Neo4j upsert failed", cause=exc) from exc
        return {"nodes": node_count, "relationships": rel_count}

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
        chunk_ids: list[UUID] | None = None,
    ) -> int:
        """Delete version-scoped nodes; orphan shared entities without MENTIONS.

        Neo4j path: detach-delete version-stamped + version node, then purge
        Entity/Topic nodes that no longer have MENTIONS edges.
        """
        driver = self._get_driver()
        chunk_id_params = [str(cid) for cid in (chunk_ids or [])]
        query = (
            "MATCH (n {tenant_id: $tenant_id}) "
            "WHERE n.node_id = $version_id "
            "OR (n.version_id = $version_id AND coalesce(n.label, '') "
            "NOT IN ['Entity','Person','Organization','Product','Ingredient',"
            "'Chemical','Regulation','Location','Concept','Topic','Community']) "
            "OR n.node_id IN $chunk_ids "
            "OR (n.label = 'Chunk' AND n.version_id = $version_id) "
            "DETACH DELETE n "
            "RETURN count(n) AS deleted"
        )
        orphan_query = (
            "MATCH (e {tenant_id: $tenant_id}) "
            "WHERE e.label IN ['Entity','Person','Organization','Product','Ingredient',"
            "'Chemical','Regulation','Location','Concept','Topic','Community'] "
            "AND NOT ( ()-[:MENTIONS]-(e) ) "
            "DETACH DELETE e "
            "RETURN count(e) AS deleted"
        )
        params = {
            "tenant_id": str(tenant.tenant_id),
            "document_id": str(document_id),
            "version_id": str(version_id),
            "chunk_ids": chunk_id_params,
        }
        require_tenant_param(params)
        try:
            with driver.session() as session:
                result = session.run(query, params)
                record = result.single()
                deleted = int(record["deleted"]) if record else 0
                orphan_result = session.run(orphan_query, {"tenant_id": str(tenant.tenant_id)})
                orphan_record = orphan_result.single()
                deleted += int(orphan_record["deleted"]) if orphan_record else 0
                return deleted
        except Exception as exc:
            raise StorageError("Neo4j delete failed", cause=exc) from exc

    async def resolve_entities(
        self,
        tenant: TenantContext,
        *,
        names: list[str],
        limit: int = 20,
    ) -> list[GraphEntityMatch]:
        normalized = [normalize_entity_name(name) for name in names if name.strip()]
        if not normalized:
            return []
        query = (
            "MATCH (n {tenant_id: $tenant_id}) "
            "WHERE n.normalized_name IN $names "
            "RETURN n.node_id AS node_id, n.canonical_name AS canonical_name, "
            "n.normalized_name AS normalized_name, n.label AS label, properties(n) AS properties "
            "LIMIT $limit"
        )
        params = {
            "tenant_id": str(tenant.tenant_id),
            "names": normalized,
            "limit": limit,
        }
        require_tenant_param(params)
        rows = self._run(query, params)
        matches: list[GraphEntityMatch] = []
        for row in rows:
            matches.append(
                GraphEntityMatch(
                    entity_id=UUID(str(row["node_id"])),
                    canonical_name=str(
                        row.get("canonical_name") or row.get("normalized_name") or ""
                    ),
                    normalized_name=str(row.get("normalized_name") or ""),
                    label=str(row.get("label") or "Entity"),
                    score=1.0,
                    properties=dict(row.get("properties") or {}),
                )
            )
        return matches

    async def neighborhood(
        self,
        tenant: TenantContext,
        *,
        seed_node_ids: list[UUID],
        depth: int = 2,
        limit: int = 50,
    ) -> list[GraphNeighborHit]:
        query = neighborhood_cypher(depth=depth)
        params = {
            "tenant_id": str(tenant.tenant_id),
            "seed_ids": [str(node_id) for node_id in seed_node_ids],
            "limit": limit,
        }
        require_tenant_param(params)
        rows = self._run(query, params)
        hits: list[GraphNeighborHit] = []
        for row in rows:
            via = row.get("via_relationship")
            hits.append(
                GraphNeighborHit(
                    node_id=UUID(str(row["node_id"])),
                    label=str(row.get("label") or ""),
                    depth=int(row.get("depth") or 0),
                    via_relationship=str(via) if via is not None else None,
                    properties=dict(row.get("properties") or {}),
                )
            )
        return hits

    async def find_claims(
        self,
        tenant: TenantContext,
        *,
        entity_ids: list[UUID] | None = None,
        document_ids: list[UUID] | None = None,
        limit: int = 20,
    ) -> list[GraphClaimHit]:
        _ = entity_ids  # subject filtering left to application when needed
        query = (
            "MATCH (c:Claim {tenant_id: $tenant_id}) "
            "OPTIONAL MATCH (c)-[:DERIVED_FROM]->(chunk:Chunk) "
            "WHERE size($document_ids) = 0 "
            "OR c.document_id IN $document_ids "
            "OR chunk.document_id IN $document_ids "
            "RETURN c.node_id AS claim_id, c.statement AS statement, c.subject AS subject, "
            "c.predicate AS predicate, c.object AS object, c.confidence AS confidence, "
            "chunk.node_id AS source_chunk_id "
            "LIMIT $limit"
        )
        params: dict[str, object] = {
            "tenant_id": str(tenant.tenant_id),
            "limit": limit,
            "document_ids": [str(item) for item in (document_ids or [])],
        }
        require_tenant_param(params)
        rows = self._run(query, params)
        claims: list[GraphClaimHit] = []
        for row in rows:
            source = row.get("source_chunk_id")
            claims.append(
                GraphClaimHit(
                    claim_id=UUID(str(row["claim_id"])),
                    statement=str(row.get("statement") or ""),
                    subject=str(row["subject"]) if row.get("subject") is not None else None,
                    predicate=str(row["predicate"]) if row.get("predicate") is not None else None,
                    object=str(row["object"]) if row.get("object") is not None else None,
                    confidence=float(row["confidence"])
                    if isinstance(row.get("confidence"), (int, float))
                    else None,
                    source_chunk_id=UUID(str(source)) if source is not None else None,
                )
            )
        return claims[:limit]

    async def find_topics(
        self,
        tenant: TenantContext,
        *,
        query_terms: list[str],
        limit: int = 20,
    ) -> list[GraphTopicHit]:
        terms = [normalize_entity_name(term) for term in query_terms if term.strip()]
        query = (
            "MATCH (t {tenant_id: $tenant_id}) "
            "WHERE t.label IN ['Topic', 'Community'] "
            "AND (size($terms) = 0 OR t.normalized_name IN $terms "
            "OR any(term IN $terms WHERE t.normalized_name CONTAINS term)) "
            "RETURN t.node_id AS topic_id, t.name AS name, t.normalized_name AS normalized_name, "
            "t.label AS label, properties(t) AS properties "
            "LIMIT $limit"
        )
        params = {
            "tenant_id": str(tenant.tenant_id),
            "terms": terms,
            "limit": limit,
        }
        require_tenant_param(params)
        rows = self._run(query, params)
        hits: list[GraphTopicHit] = []
        for row in rows:
            hits.append(
                GraphTopicHit(
                    topic_id=UUID(str(row["topic_id"])),
                    name=str(row.get("name") or row.get("normalized_name") or ""),
                    normalized_name=str(row.get("normalized_name") or ""),
                    label=str(row.get("label") or "Topic"),
                    score=1.0,
                    properties=dict(row.get("properties") or {}),
                )
            )
        return hits

    async def chunk_ids_for_nodes(
        self,
        tenant: TenantContext,
        *,
        node_ids: list[UUID],
        limit: int = 50,
    ) -> list[UUID]:
        query = (
            "MATCH (n {tenant_id: $tenant_id}) "
            "WHERE n.node_id IN $node_ids "
            "OPTIONAL MATCH (n)-[r]-(other) "
            "WHERE type(r) IN ['MENTIONS', 'DERIVED_FROM', 'HAS_CHUNK'] "
            "WITH collect(DISTINCT n.node_id) + collect(DISTINCT other.node_id) "
            "+ collect(DISTINCT r.chunk_id) AS ids "
            "UNWIND ids AS raw_id "
            "WITH raw_id WHERE raw_id IS NOT NULL "
            "MATCH (c:Chunk {tenant_id: $tenant_id, node_id: raw_id}) "
            "RETURN DISTINCT c.node_id AS chunk_id "
            "LIMIT $limit"
        )
        params = {
            "tenant_id": str(tenant.tenant_id),
            "node_ids": [str(node_id) for node_id in node_ids],
            "limit": limit,
        }
        require_tenant_param(params)
        rows = self._run(query, params)
        return [UUID(str(row["chunk_id"])) for row in rows if row.get("chunk_id")]

    def _run(self, query: str, params: dict[str, object]) -> list[dict[str, Any]]:
        driver = self._get_driver()
        try:
            with driver.session() as session:
                result = session.run(query, params)
                return [dict(record) for record in result]
        except (AuthorizationError, ConfigurationError):
            raise
        except Exception as exc:
            raise StorageError("Neo4j query failed", cause=exc) from exc


def _jsonable(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    return value
