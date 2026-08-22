"""Graph store protocol for Neo4j projection and retrieval queries."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from graph_rag.domain.graph.models import ProjectedGraph
from graph_rag.domain.graph.query import (
    GraphClaimHit,
    GraphEntityMatch,
    GraphNeighborHit,
    GraphTopicHit,
)
from graph_rag.domain.tenant import TenantContext


class GraphStore(Protocol):
    """Tenant-aware graph persistence and query port."""

    async def upsert_graph(
        self,
        tenant: TenantContext,
        graph: ProjectedGraph,
    ) -> dict[str, int]:
        """Upsert nodes and relationships. Returns counts."""
        ...

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
        chunk_ids: list[UUID] | None = None,
    ) -> int:
        """Delete version-scoped graph data and orphan shared entities only.

        Shared Entity/Topic nodes are removed only when no MENTIONS remain from
        surviving chunks. Returns total deleted node+relationship count.
        """
        ...

    async def resolve_entities(
        self,
        tenant: TenantContext,
        *,
        names: list[str],
        limit: int = 20,
    ) -> list[GraphEntityMatch]:
        """Resolve query mentions to canonical entity nodes."""
        ...

    async def neighborhood(
        self,
        tenant: TenantContext,
        *,
        seed_node_ids: list[UUID],
        depth: int = 2,
        limit: int = 50,
    ) -> list[GraphNeighborHit]:
        """Bounded multi-hop neighborhood around seed nodes."""
        ...

    async def find_claims(
        self,
        tenant: TenantContext,
        *,
        entity_ids: list[UUID] | None = None,
        limit: int = 20,
    ) -> list[GraphClaimHit]:
        """Return claims, optionally linked to entities via shared chunks."""
        ...

    async def find_topics(
        self,
        tenant: TenantContext,
        *,
        query_terms: list[str],
        limit: int = 20,
    ) -> list[GraphTopicHit]:
        """Find topics / communities matching query terms."""
        ...

    async def chunk_ids_for_nodes(
        self,
        tenant: TenantContext,
        *,
        node_ids: list[UUID],
        limit: int = 50,
    ) -> list[UUID]:
        """Map graph nodes to related chunk IDs via MENTIONS / DERIVED_FROM."""
        ...
