"""Structural and entity graph paths stay inside the selected documents."""

from __future__ import annotations

from uuid import UUID

import pytest

from graph_rag.application.retrieval import RetrieveEvidenceService
from graph_rag.domain.chunks.models import ChunkBase, ChunkType
from graph_rag.domain.chunks.vectors import (
    ChunkVectorPayload,
    VectorSearchHit,
    VectorSearchRequest,
)
from graph_rag.domain.graph.cypher_safety import structural_neighborhood_cypher
from graph_rag.domain.graph.models import GraphNode, GraphRelationship, ProjectedGraph
from graph_rag.domain.graph.vocabulary import (
    SemanticNodeLabel,
    SemanticRelationshipType,
    StructuralNodeLabel,
    StructuralRelationshipType,
)
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.retrieval import RetrievalFilters, RetrievalMode, RetrievalRequest
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.models import FakeEmbeddingModel
from graph_rag.infrastructure.persistence.chunks import InMemoryChunkLookupStore
from graph_rag.infrastructure.persistence.neo4j.memory import InMemoryGraphStore
from graph_rag.infrastructure.persistence.neo4j.repository import Neo4jGraphStore


def _chunk(
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    text: str,
) -> ChunkBase:
    return ChunkBase(
        chunk_id=new_id(),
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        modality=Modality.TEXT,
        chunk_type=ChunkType.TEXT,
        text=text,
        token_count=max(1, len(text.split())),
        page_start=1,
        page_end=1,
        section_path=["Body"],
        source_object_keys=["tenant/doc/original.pdf"],
        content_hash=content_sha256_hex(text),
    )


class AssignedScoreStore:
    def __init__(self, hits: list[VectorSearchHit]) -> None:
        self.hits = hits

    async def search(
        self,
        tenant: TenantContext,
        request: VectorSearchRequest,
    ) -> list[VectorSearchHit]:
        allowed = set(request.document_ids)
        return [
            hit
            for hit in self.hits
            if hit.payload.tenant_id == tenant.tenant_id
            and (not allowed or hit.payload.document_id in allowed)
        ][: request.top_k]


def _hit(chunk: ChunkBase, score: float) -> VectorSearchHit:
    return VectorSearchHit(
        point_id=chunk.chunk_id,
        score=score,
        payload=ChunkVectorPayload(
            tenant_id=chunk.tenant_id,
            document_id=chunk.document_id,
            version_id=chunk.version_id,
            chunk_id=chunk.chunk_id,
            modality=chunk.modality,
            chunk_type=chunk.chunk_type,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            content_hash=chunk.content_hash,
            source_object_keys=list(chunk.source_object_keys),
            text_preview=chunk.text,
        ),
        chunk=chunk,
    )


@pytest.mark.asyncio
async def test_structural_path_is_limited_to_the_selected_document() -> None:
    tenant = TenantContext(tenant_id=new_id())
    other_tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    other_document_id = new_id()
    version_id = new_id()
    selected = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="SelectedDocumentPassage",
    )
    other = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=other_document_id,
        version_id=version_id,
        text="OtherDocumentPassage",
    )
    graph = InMemoryGraphStore()
    await graph.upsert_graph(
        tenant,
        ProjectedGraph(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            nodes=[
                GraphNode(
                    node_id=document_id,
                    label=StructuralNodeLabel.DOCUMENT.value,
                    tenant_id=tenant.tenant_id,
                    properties={"document_id": str(document_id)},
                ),
                GraphNode(
                    node_id=selected.chunk_id,
                    label=StructuralNodeLabel.CHUNK.value,
                    tenant_id=tenant.tenant_id,
                    properties={
                        "document_id": str(document_id),
                        "chunk_id": str(selected.chunk_id),
                    },
                ),
            ],
            relationships=[
                GraphRelationship(
                    relationship_id=new_id(),
                    relationship_type=StructuralRelationshipType.HAS_CHUNK.value,
                    tenant_id=tenant.tenant_id,
                    source_node_id=document_id,
                    target_node_id=selected.chunk_id,
                )
            ],
        ),
    )
    await graph.upsert_graph(
        tenant,
        ProjectedGraph(
            tenant_id=tenant.tenant_id,
            document_id=other_document_id,
            version_id=version_id,
            nodes=[
                GraphNode(
                    node_id=other.chunk_id,
                    label=StructuralNodeLabel.CHUNK.value,
                    tenant_id=tenant.tenant_id,
                    properties={
                        "document_id": str(other_document_id),
                        "chunk_id": str(other.chunk_id),
                    },
                )
            ],
            relationships=[],
        ),
    )
    hits = await graph.structural_neighborhood(
        tenant,
        document_ids=[document_id],
    )
    assert {str(hit.properties["document_id"]) for hit in hits} == {str(document_id)}
    assert await graph.structural_neighborhood(other_tenant, document_ids=[document_id]) == []

    chunks = InMemoryChunkLookupStore()
    await chunks.upsert(tenant, [selected, other])
    service = RetrieveEvidenceService(
        embedding_model=FakeEmbeddingModel(),
        vector_store=AssignedScoreStore([_hit(selected, 0.5)]),
        chunk_store=chunks,
        graph_store=graph,
    )
    outcome = await service.retrieve(
        tenant,
        RetrievalRequest(
            question="it",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[document_id]),
            include_graph_paths=True,
            rerank=False,
        ),
    )
    assert outcome.result.graph_paths
    assert outcome.result.graph_paths[0].metadata["path_kind"] == "structural"
    joined = " ".join(outcome.result.graph_paths[0].nodes)
    assert str(other.chunk_id) not in joined
    assert "OtherDocumentPassage" not in {item.text for item in outcome.result.evidence}
    assert "graph_no_structural_path" not in outcome.result.warnings


@pytest.mark.asyncio
async def test_entity_path_kind_and_missing_graph_reasons() -> None:
    tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    version_id = new_id()
    chunk = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Silicone oil viscosity decreases with temperature.",
    )
    entity_id = new_id()
    graph = InMemoryGraphStore()
    await graph.upsert_graph(
        tenant,
        ProjectedGraph(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            nodes=[
                GraphNode(
                    node_id=chunk.chunk_id,
                    label=StructuralNodeLabel.CHUNK.value,
                    tenant_id=tenant.tenant_id,
                    properties={
                        "chunk_id": str(chunk.chunk_id),
                        "document_id": str(document_id),
                    },
                ),
                GraphNode(
                    node_id=entity_id,
                    label=SemanticNodeLabel.CHEMICAL.value,
                    tenant_id=tenant.tenant_id,
                    properties={
                        "canonical_name": "silicone oil",
                        "normalized_name": "silicone oil",
                    },
                ),
            ],
            relationships=[
                GraphRelationship(
                    relationship_id=new_id(),
                    relationship_type=SemanticRelationshipType.MENTIONS.value,
                    tenant_id=tenant.tenant_id,
                    source_node_id=chunk.chunk_id,
                    target_node_id=entity_id,
                )
            ],
        ),
    )
    chunks = InMemoryChunkLookupStore()
    await chunks.upsert(tenant, [chunk])
    service = RetrieveEvidenceService(
        embedding_model=FakeEmbeddingModel(),
        vector_store=AssignedScoreStore([_hit(chunk, 0.2)]),
        chunk_store=chunks,
        graph_store=graph,
    )
    outcome = await service.retrieve(
        tenant,
        RetrievalRequest(
            question="How is silicone oil related to temperature?",
            mode=RetrievalMode.LOCAL,
            include_graph_paths=True,
            rerank=False,
        ),
    )
    assert outcome.result.graph_paths[0].metadata["path_kind"] == "entity"

    disabled = RetrieveEvidenceService(
        embedding_model=FakeEmbeddingModel(),
        vector_store=AssignedScoreStore([_hit(chunk, 0.2)]),
        chunk_store=chunks,
        graph_store=None,
    )
    missing = await disabled.retrieve(
        tenant,
        RetrievalRequest(
            question="How is silicone oil related to temperature?",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[document_id]),
            include_graph_paths=True,
            rerank=False,
        ),
    )
    assert missing.result.graph_paths == []
    assert "graph_not_stored" in missing.result.warnings

    empty_graph = InMemoryGraphStore()
    no_path = RetrieveEvidenceService(
        embedding_model=FakeEmbeddingModel(),
        vector_store=AssignedScoreStore([_hit(chunk, 0.2)]),
        chunk_store=chunks,
        graph_store=empty_graph,
    )
    structural_miss = await no_path.retrieve(
        tenant,
        RetrievalRequest(
            question="it",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[document_id]),
            include_graph_paths=True,
            rerank=False,
        ),
    )
    assert structural_miss.result.graph_paths == []
    assert structural_miss.result.warnings.count("graph_no_structural_path") == 1

    entity_miss = await no_path.retrieve(
        tenant,
        RetrievalRequest(
            question="Where is silicone oil mentioned?",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[document_id]),
            include_graph_paths=True,
            rerank=False,
        ),
    )
    assert "graph_no_entity_match" in entity_miss.result.warnings
    assert "graph_no_structural_path" not in entity_miss.result.warnings


@pytest.mark.asyncio
async def test_neo4j_structural_neighborhood_drops_other_documents() -> None:
    cypher = structural_neighborhood_cypher()
    assert "tenant_id: $tenant_id" in cypher
    assert "n.document_id IN $document_ids" in cypher
    tenant = TenantContext(tenant_id=new_id())
    selected = new_id()
    outsider = new_id()
    selected_node = new_id()
    outsider_node = new_id()
    seen: list[tuple[str, dict[str, object]]] = []

    class _Session:
        def run(self, query: str, params: dict[str, object]) -> list[dict[str, object]]:
            seen.append((query, params))
            return [
                {
                    "node_id": str(selected_node),
                    "label": "Chunk",
                    "via_relationship": "HAS_CHUNK",
                    "properties": {"document_id": str(selected)},
                },
                {
                    "node_id": str(outsider_node),
                    "label": "Chunk",
                    "via_relationship": "HAS_CHUNK",
                    "properties": {"document_id": str(outsider)},
                },
            ]

        def __enter__(self) -> _Session:
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

    class _Driver:
        def session(self) -> _Session:
            return _Session()

    store = Neo4jGraphStore(driver=_Driver())
    assert await store.structural_neighborhood(tenant, document_ids=[]) == []
    hits = await store.structural_neighborhood(tenant, document_ids=[selected])
    assert [hit.node_id for hit in hits] == [selected_node]
    assert seen
    assert seen[0][1]["document_ids"] == [str(selected)]
