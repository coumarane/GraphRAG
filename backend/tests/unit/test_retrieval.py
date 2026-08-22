"""Retrieval modes, fusion, expansion and evidence assembly tests."""

from __future__ import annotations

import pytest

from graph_rag.application.chunking import EmbedChunksService
from graph_rag.application.retrieval import RetrieveEvidenceService
from graph_rag.domain.chunks.models import ChunkBase, ChunkType
from graph_rag.domain.graph.models import GraphNode, GraphRelationship, ProjectedGraph
from graph_rag.domain.graph.vocabulary import (
    SemanticNodeLabel,
    SemanticRelationshipType,
    StructuralNodeLabel,
    StructuralRelationshipType,
)
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.retrieval import (
    RetrievalFilters,
    RetrievalMode,
    RetrievalRequest,
    analyze_query,
    expand_parents_and_neighbors,
    reciprocal_rank_fusion,
)
from graph_rag.domain.retrieval.assembly import chunk_to_evidence
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.models import FakeEmbeddingModel, FakeReranker
from graph_rag.infrastructure.persistence.chunks import (
    InMemoryChunkLookupStore,
    InMemoryLexicalSearchStore,
)
from graph_rag.infrastructure.persistence.neo4j import InMemoryGraphStore
from graph_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore


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
    assert RetrievalMode.HYBRID in analysis.selected_modes
    assert Modality.CHART in analysis.modality_hints


@pytest.mark.asyncio
async def test_auto_texture_evaluation_chart_not_multimodal_only() -> None:
    analysis = analyze_query(
        "Texture evaluation chart",
        mode=RetrievalMode.AUTO,
    )
    assert RetrievalMode.MULTIMODAL in analysis.selected_modes
    assert RetrievalMode.HYBRID in analysis.selected_modes
    lowered = analysis.normalized_question.casefold()
    assert "miu" in lowered or "friction" in lowered or "smoothness" in lowered
    assert "silkyflake" not in lowered


@pytest.mark.asyncio
async def test_analyze_query_uses_current_question_not_chat_history() -> None:
    wrapped = "\n".join(
        [
            "Conversation so far:",
            "User: Give me heavy metal content for METASHINE RC HC ZC",
            "Assistant: RC series Cd 0.4 ppm Pb <3 ppm",
            "",
            "Current question: Texture evaluation chart",
            "",
            "Answer the current question using retrieved document evidence.",
        ]
    )
    analysis = analyze_query(wrapped, mode=RetrievalMode.AUTO)
    assert "texture" in analysis.normalized_question.casefold()
    assert "metashine" not in analysis.normalized_question.casefold()
    assert "assay" not in analysis.intent_labels
    assert RetrievalMode.HYBRID in analysis.selected_modes


@pytest.mark.asyncio
async def test_condition_range_query_prefers_chart_modality() -> None:
    analysis = analyze_query(
        "Over which pH range was the tinting test performed?",
        mode=RetrievalMode.AUTO,
    )
    assert analysis.features.asks_condition_range
    assert analysis.features.prefer_chart
    assert Modality.CHART in analysis.modality_hints
    assert Modality.TABLE not in analysis.modality_hints


@pytest.mark.asyncio
async def test_tinting_ph_range_prefers_axis_not_mic_table() -> None:
    tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    version_id = new_id()
    axis = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text=(
            "Effect of pH values in aqueous solution\n"
            "pH 3.0 4.0 5.0 6.0 7.0 8.0 9.0 10.0\n"
            "Little/No tinting under alkaline conditions"
        ),
        modality=Modality.CHART,
        chunk_type=ChunkType.CHART,
        page_start=10,
        page_end=10,
        document_name="SY-KNP.pdf",
    )
    mic = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="MIC minimum inhibitory concentration at pH 5, pH 7, pH 9 — no growth",
        modality=Modality.TABLE,
        chunk_type=ChunkType.TABLE,
        page_start=8,
        page_end=8,
        document_name="SY-KNP.pdf",
    )
    chunk_store = InMemoryChunkLookupStore()
    await chunk_store.upsert(tenant, [axis, mic])
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    embedded = await EmbedChunksService(embedder).embed([axis, mic])
    await vectors.upsert(tenant, embedded.records)
    lexical = InMemoryLexicalSearchStore()
    await lexical.upsert(tenant, [axis, mic])
    service = RetrieveEvidenceService(
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=chunk_store,
        lexical_store=lexical,
        reranker=FakeReranker(),
    )
    outcome = await service.retrieve(
        tenant,
        RetrievalRequest(
            question="Over which pH range was the tinting test performed?",
            mode=RetrievalMode.AUTO,
            top_k=4,
            rerank=False,
        ),
    )
    assert outcome.result.evidence
    top = outcome.result.evidence[0]
    lowered = (top.text or "").casefold()
    assert "tint" in lowered or "3.0" in lowered or "10.0" in lowered
    assert "minimum inhibitory" not in lowered


@pytest.mark.asyncio
async def test_solar_radiation_expands_to_nir_synonyms() -> None:
    analysis = analyze_query("solar radiation data", mode=RetrievalMode.AUTO)
    lowered = analysis.normalized_question.casefold()
    assert "near-infrared" in lowered or "nir" in lowered
    assert Modality.DIAGRAM in analysis.modality_hints


@pytest.mark.asyncio
async def test_texture_evaluation_expands_to_generic_surface_terms() -> None:
    analysis = analyze_query(
        "Texture evaluation chart MIU MMD",
        mode=RetrievalMode.AUTO,
    )
    lowered = analysis.normalized_question.casefold()
    assert "friction" in lowered or "smoothness" in lowered
    assert "surface" in lowered
    # Must not inject brochure-specific product SKUs.
    assert "ftd008fy" not in lowered
    assert "silkyflake" not in lowered


@pytest.mark.asyncio
async def test_auto_selects_assay_modes_for_heavy_metal_content() -> None:
    analysis = analyze_query(
        "Give me the heavy metal content",
        mode=RetrievalMode.AUTO,
    )
    assert "assay" in analysis.intent_labels
    assert Modality.TABLE in analysis.modality_hints
    assert RetrievalMode.HYBRID in analysis.selected_modes
    assert RetrievalMode.MULTIMODAL in analysis.selected_modes


@pytest.mark.asyncio
async def test_heuristic_reranker_prefers_assay_over_coating() -> None:
    from graph_rag.domain.models.contracts import RerankItem, RerankRequest
    from graph_rag.infrastructure.models import HeuristicReranker

    reranker = HeuristicReranker()
    response = await reranker.rerank(
        RerankRequest(
            query="Give me the heavy metal content",
            items=[
                RerankItem(
                    id="coating",
                    text="TC series Fe2O3 coated series deep interference effects",
                    metadata={"modality": "text"},
                ),
                RerankItem(
                    id="assay",
                    text="Heavy metal content Cd 0.4 ppm As 0.7 ppm Pb <3 ppm N.D.",
                    metadata={"modality": "table"},
                ),
            ],
            top_n=2,
        )
    )
    assert response.results[0].id == "assay"


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
async def test_local_graph_retrieval_respects_document_scope() -> None:
    """Two unrelated products both mention "water" as an ingredient, so the
    graph entity node they share links to chunks in both documents. A request
    pinned to product A's document must not surface product B's chunk via that
    shared entity — regression for a real production bug: a query naming one
    product returned a completely unrelated product's ingredient table because
    LOCAL graph traversal ignored request.filters.document_ids entirely.
    """
    tenant = TenantContext(tenant_id=new_id())
    doc_a, version_a = new_id(), new_id()
    doc_b, version_b = new_id(), new_id()
    chunk_a = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=doc_a,
        version_id=version_a,
        text="Product A composition: OCTYLDODECETH-20, 100%.",
    )
    chunk_b = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=doc_b,
        version_id=version_b,
        text="Product B toner formulation: Butylene Glycol 6.0%, water to 100%.",
    )
    entity_id = new_id()
    graph = InMemoryGraphStore()
    await graph.upsert_graph(
        tenant,
        ProjectedGraph(
            tenant_id=tenant.tenant_id,
            document_id=doc_a,
            version_id=version_a,
            nodes=[
                GraphNode(
                    node_id=chunk_a.chunk_id,
                    label=StructuralNodeLabel.CHUNK.value,
                    tenant_id=tenant.tenant_id,
                    properties={"chunk_id": str(chunk_a.chunk_id)},
                ),
                GraphNode(
                    node_id=entity_id,
                    label=SemanticNodeLabel.CHEMICAL.value,
                    tenant_id=tenant.tenant_id,
                    properties={"canonical_name": "water", "normalized_name": "water"},
                ),
            ],
            relationships=[
                GraphRelationship(
                    relationship_id=new_id(),
                    relationship_type=SemanticRelationshipType.MENTIONS.value,
                    tenant_id=tenant.tenant_id,
                    source_node_id=chunk_a.chunk_id,
                    target_node_id=entity_id,
                ),
            ],
        ),
    )
    await graph.upsert_graph(
        tenant,
        ProjectedGraph(
            tenant_id=tenant.tenant_id,
            document_id=doc_b,
            version_id=version_b,
            nodes=[
                GraphNode(
                    node_id=chunk_b.chunk_id,
                    label=StructuralNodeLabel.CHUNK.value,
                    tenant_id=tenant.tenant_id,
                    properties={"chunk_id": str(chunk_b.chunk_id)},
                ),
            ],
            relationships=[
                GraphRelationship(
                    relationship_id=new_id(),
                    relationship_type=SemanticRelationshipType.MENTIONS.value,
                    tenant_id=tenant.tenant_id,
                    source_node_id=chunk_b.chunk_id,
                    target_node_id=entity_id,
                ),
            ],
        ),
    )
    chunk_store = InMemoryChunkLookupStore()
    await chunk_store.upsert(tenant, [chunk_a, chunk_b])
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    await vectors.upsert(
        tenant,
        (await EmbedChunksService(embedder).embed([chunk_a, chunk_b])).records,
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
            question="What water content does Product A have?",
            mode=RetrievalMode.LOCAL,
            filters=RetrievalFilters(document_ids=[doc_a]),
            top_k=5,
            graph_depth=2,
            rerank=False,
        ),
    )
    document_ids = {item.document_id for item in outcome.result.evidence}
    assert document_ids == {doc_a}
    assert chunk_b.chunk_id not in {item.chunk_id for item in outcome.result.evidence}


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
