"""Retrieval modes, fusion, expansion and evidence assembly tests."""

from __future__ import annotations

import pytest

from enterprise_rag.application.chunking import EmbedChunksService
from enterprise_rag.application.retrieval import RetrieveEvidenceService
from enterprise_rag.domain.chunks.models import ChunkBase, ChunkType
from enterprise_rag.domain.graph.models import GraphNode, GraphRelationship, ProjectedGraph
from enterprise_rag.domain.graph.vocabulary import (
    SemanticNodeLabel,
    SemanticRelationshipType,
    StructuralNodeLabel,
    StructuralRelationshipType,
)
from enterprise_rag.domain.ids import content_sha256_hex, new_id
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.retrieval import (
    RetrievalMode,
    RetrievalRequest,
    analyze_query,
    expand_parents_and_neighbors,
    reciprocal_rank_fusion,
)
from enterprise_rag.domain.retrieval.assembly import chunk_to_evidence
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.models import FakeEmbeddingModel, FakeReranker
from enterprise_rag.infrastructure.persistence.chunks import (
    InMemoryChunkLookupStore,
    InMemoryLexicalSearchStore,
)
from enterprise_rag.infrastructure.persistence.neo4j import InMemoryGraphStore
from enterprise_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore


def _hash(text: str) -> str:
    return content_sha256_hex(text)


def _chunk(
    *,
    tenant_id,
    document_id,
    version_id,
    text: str,
    modality: Modality = Modality.TEXT,
    chunk_type: ChunkType = ChunkType.TEXT,
    parent_chunk_id=None,
    page_start: int = 1,
    page_end: int = 1,
    document_name: str = "spec.pdf",
) -> ChunkBase:
    return ChunkBase(
        chunk_id=new_id(),
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        parent_chunk_id=parent_chunk_id,
        modality=modality,
        chunk_type=chunk_type,
        text=text,
        token_count=max(1, len(text.split())),
        page_start=page_start,
        page_end=page_end,
        section_path=["Results"],
        source_object_keys=["tenant/doc/v1/original.pdf"],
        content_hash=_hash(text),
        metadata={"document_name": document_name},
    )


@pytest.mark.asyncio
async def test_auto_selects_multimodal_for_chart_questions() -> None:
    analysis = analyze_query(
        "What does the chart show about viscosity?",
        mode=RetrievalMode.AUTO,
    )
    assert RetrievalMode.MULTIMODAL in analysis.selected_modes
    assert Modality.CHART in analysis.modality_hints


@pytest.mark.asyncio
async def test_naive_retrieval_with_parent_expansion_and_rerank() -> None:
    tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    version_id = new_id()
    parent = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Parent section covering viscosity measurements across temperatures.",
        chunk_type=ChunkType.SECTION,
    )
    child = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Measured viscosity declined with temperature.",
        parent_chunk_id=parent.chunk_id,
    )
    sibling = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Calibration used silicone oil reference.",
        parent_chunk_id=parent.chunk_id,
        page_start=1,
    )

    chunk_store = InMemoryChunkLookupStore()
    await chunk_store.upsert(tenant, [parent, child, sibling])

    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    embed_service = EmbedChunksService(embedder, include_parents=True)
    embedded = await embed_service.embed([parent, child, sibling])
    await vectors.upsert(tenant, embedded.records)

    lexical = InMemoryLexicalSearchStore()
    await lexical.upsert(tenant, [parent, child, sibling])

    service = RetrieveEvidenceService(
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=chunk_store,
        lexical_store=lexical,
        reranker=FakeReranker(),
        document_names={document_id: "spec.pdf"},
    )
    outcome = await service.retrieve(
        tenant,
        RetrievalRequest(
            question="What is the recommended viscosity temperature trend?",
            mode=RetrievalMode.NAIVE,
            top_k=5,
            rerank=True,
        ),
    )
    assert outcome.result.evidence
    chunk_ids = {item.chunk_id for item in outcome.result.evidence}
    assert child.chunk_id in chunk_ids or parent.chunk_id in chunk_ids
    assert outcome.result.retrieval_trace_id


@pytest.mark.asyncio
async def test_hybrid_fuses_dense_and_lexical() -> None:
    tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    version_id = new_id()
    relevant = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Storage temperature should remain below 25 Celsius.",
    )
    other = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Packaging uses amber glass bottles.",
    )
    chunk_store = InMemoryChunkLookupStore()
    await chunk_store.upsert(tenant, [relevant, other])
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    records = (await EmbedChunksService(embedder).embed([relevant, other])).records
    await vectors.upsert(tenant, records)
    lexical = InMemoryLexicalSearchStore()
    await lexical.upsert(tenant, [relevant, other])

    service = RetrieveEvidenceService(
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=chunk_store,
        lexical_store=lexical,
    )
    outcome = await service.retrieve(
        tenant,
        RetrievalRequest(
            question="recommended storage temperature",
            mode=RetrievalMode.HYBRID,
            top_k=3,
            rerank=False,
        ),
    )
    assert outcome.result.evidence
    assert outcome.branch_counts.get("hybrid", 0) >= 1
    assert any("storage" in item.text.casefold() for item in outcome.result.evidence)


@pytest.mark.asyncio
async def test_local_graph_retrieval_returns_mentioned_chunks() -> None:
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
    claim_id = new_id()
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
                    properties={"chunk_id": str(chunk.chunk_id)},
                ),
                GraphNode(
                    node_id=entity_id,
                    label=SemanticNodeLabel.CHEMICAL.value,
                    tenant_id=tenant.tenant_id,
                    properties={
                        "canonical_name": "silicone oil",
                        "normalized_name": "silicone oil",
                        "aliases": ["PDMS"],
                    },
                ),
                GraphNode(
                    node_id=claim_id,
                    label=SemanticNodeLabel.CLAIM.value,
                    tenant_id=tenant.tenant_id,
                    properties={
                        "statement": "Viscosity decreases as temperature rises",
                        "subject": "silicone oil",
                        "predicate": "decreases_with",
                        "object": "temperature",
                        "confidence": 0.9,
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
                ),
                GraphRelationship(
                    relationship_id=new_id(),
                    relationship_type=StructuralRelationshipType.DERIVED_FROM.value,
                    tenant_id=tenant.tenant_id,
                    source_node_id=claim_id,
                    target_node_id=chunk.chunk_id,
                ),
            ],
        ),
    )
    chunk_store = InMemoryChunkLookupStore()
    await chunk_store.upsert(tenant, [chunk])
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    embedder = FakeEmbeddingModel()
    await vectors.upsert(
        tenant,
        (await EmbedChunksService(embedder).embed([chunk])).records,
    )

    service = RetrieveEvidenceService(
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=chunk_store,
        graph_store=graph,
    )
    outcome = await service.retrieve(
        tenant,
        RetrievalRequest(
            question="How is silicone oil related to temperature?",
            mode=RetrievalMode.LOCAL,
            top_k=5,
            graph_depth=2,
            include_graph_paths=True,
            rerank=False,
        ),
    )
    assert any(item.chunk_id == chunk.chunk_id for item in outcome.result.evidence)
    assert outcome.result.graph_paths


@pytest.mark.asyncio
async def test_multimodal_filters_modalities() -> None:
    tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    version_id = new_id()
    text_chunk = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Narrative text about lab practice.",
    )
    chart_chunk = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Chart showing viscosity falling with temperature.",
        modality=Modality.CHART,
        chunk_type=ChunkType.CHART,
    )
    chunk_store = InMemoryChunkLookupStore()
    await chunk_store.upsert(tenant, [text_chunk, chart_chunk])
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    await vectors.upsert(
        tenant,
        (await EmbedChunksService(embedder).embed([text_chunk, chart_chunk])).records,
    )
    service = RetrieveEvidenceService(
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=chunk_store,
    )
    outcome = await service.retrieve(
        tenant,
        RetrievalRequest(
            question="What does the chart show about viscosity?",
            mode=RetrievalMode.MULTIMODAL,
            top_k=3,
            rerank=False,
        ),
    )
    assert outcome.result.evidence
    assert any(item.modality is Modality.CHART for item in outcome.result.evidence)
    assert outcome.result.evidence[0].modality is Modality.CHART


def test_rrf_and_parent_expansion_helpers() -> None:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    parent = _chunk(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="parent body",
        chunk_type=ChunkType.SECTION,
    )
    child = _chunk(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="child body",
        parent_chunk_id=parent.chunk_id,
    )
    a = chunk_to_evidence(child, score=0.9, score_components={"dense": 0.9})
    b = chunk_to_evidence(parent, score=0.5, score_components={"dense": 0.5})
    fused = reciprocal_rank_fusion([[a], [b, a]])
    assert fused[0].chunk_id in {child.chunk_id, parent.chunk_id}
    expanded = expand_parents_and_neighbors(
        [a],
        {parent.chunk_id: parent, child.chunk_id: child},
    )
    assert {item.chunk_id for item in expanded} >= {child.chunk_id, parent.chunk_id}


@pytest.mark.asyncio
async def test_mix_runs_multiple_branches() -> None:
    tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    version_id = new_id()
    chunk = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Global summary of supplier safety limits.",
        chunk_type=ChunkType.DOCUMENT_SUMMARY,
    )
    topic_id = new_id()
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
                    properties={"chunk_id": str(chunk.chunk_id)},
                ),
                GraphNode(
                    node_id=topic_id,
                    label=SemanticNodeLabel.TOPIC.value,
                    tenant_id=tenant.tenant_id,
                    properties={"name": "safety", "normalized_name": "safety"},
                ),
            ],
            relationships=[
                GraphRelationship(
                    relationship_id=new_id(),
                    relationship_type=SemanticRelationshipType.MENTIONS.value,
                    tenant_id=tenant.tenant_id,
                    source_node_id=chunk.chunk_id,
                    target_node_id=topic_id,
                )
            ],
        ),
    )
    chunk_store = InMemoryChunkLookupStore()
    await chunk_store.upsert(tenant, [chunk])
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    await vectors.upsert(tenant, (await EmbedChunksService(embedder).embed([chunk])).records)
    lexical = InMemoryLexicalSearchStore()
    await lexical.upsert(tenant, [chunk])

    service = RetrieveEvidenceService(
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=chunk_store,
        graph_store=graph,
        lexical_store=lexical,
    )
    outcome = await service.retrieve(
        tenant,
        RetrievalRequest(
            question="Compare the safety limits across all suppliers.",
            mode=RetrievalMode.MIX,
            top_k=5,
            include_graph_paths=True,
            rerank=False,
        ),
    )
    assert outcome.result.mode is RetrievalMode.MIX
    assert len(outcome.branch_counts) >= 2
    assert outcome.result.evidence
