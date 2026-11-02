"""Nested fusion keeps retriever scores, and rejected evidence stays rejected."""

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
from graph_rag.domain.generation.grounding_policy import (
    SELECTION_HAS_NO_SUPPORTING_EVIDENCE,
    retriever_score,
)
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.retrieval import RetrievalFilters, RetrievalMode, RetrievalRequest
from graph_rag.domain.retrieval.assembly import chunk_to_evidence
from graph_rag.domain.retrieval.fusion import reciprocal_rank_fusion
from graph_rag.domain.retrieval.protocols import LexicalHit
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.models import FakeEmbeddingModel
from graph_rag.infrastructure.persistence.chunks import InMemoryChunkLookupStore

KEPT = "KeptAssignedPassage"
REJECTED_CHILD = "RejectedBelowFloorChild"
REJECTED_PARENT = "RejectedParentMustStayOut"
REJECTED_NEIGHBOR = "RejectedNeighborMustStayOut"
OTHER_DOCUMENT = "OtherDocumentMustStayOut"

_CASES = (
    (
        "factual",
        "Where is the packing note kept?",
        RetrievalMode.AUTO,
        (RetrievalMode.NAIVE, RetrievalMode.HYBRID),
    ),
    (
        "assay",
        "What is the assay specification for heavy metals?",
        RetrievalMode.AUTO,
        (RetrievalMode.HYBRID, RetrievalMode.MULTIMODAL, RetrievalMode.NAIVE),
    ),
    (
        "multimodal",
        "What does the chart show?",
        RetrievalMode.AUTO,
        (RetrievalMode.NAIVE, RetrievalMode.MULTIMODAL, RetrievalMode.HYBRID),
    ),
    (
        "mix",
        "Where is the packing note kept?",
        RetrievalMode.MIX,
        (
            RetrievalMode.LOCAL,
            RetrievalMode.GLOBAL,
            RetrievalMode.NAIVE,
            RetrievalMode.MULTIMODAL,
            RetrievalMode.HYBRID,
        ),
    ),
)


def _chunk(
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    text: str,
    page_start: int,
    page_end: int,
    parent_chunk_id: UUID | None = None,
) -> ChunkBase:
    return ChunkBase(
        chunk_id=new_id(),
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        parent_chunk_id=parent_chunk_id,
        modality=Modality.TEXT,
        chunk_type=ChunkType.SECTION if parent_chunk_id is None else ChunkType.TEXT,
        text=text,
        token_count=max(1, len(text.split())),
        page_start=page_start,
        page_end=page_end,
        section_path=["Body"],
        source_object_keys=["tenant/doc/original.pdf"],
        content_hash=content_sha256_hex(text),
    )


def _hit(chunk: ChunkBase, score: float) -> VectorSearchHit:
    return VectorSearchHit(
        point_id=chunk.chunk_id,
        score=score,
        payload=ChunkVectorPayload(
            tenant_id=chunk.tenant_id,
            document_id=chunk.document_id,
            version_id=chunk.version_id,
            chunk_id=chunk.chunk_id,
            parent_chunk_id=chunk.parent_chunk_id,
            modality=chunk.modality,
            chunk_type=chunk.chunk_type,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section_path=list(chunk.section_path),
            content_hash=chunk.content_hash,
            source_object_keys=list(chunk.source_object_keys),
            text_preview=chunk.text,
        ),
        chunk=chunk,
    )


def _qualification(components: dict[str, float]) -> list[float]:
    return [value for key, value in components.items() if key.startswith("source_score_")]


class AssignedScoreStore:
    def __init__(self, hits: list[VectorSearchHit]) -> None:
        self.hits = hits

    async def ensure_collection(self, *, vector_size: int) -> None:
        return None

    async def upsert(self, tenant: TenantContext, records: list[object]) -> int:
        return 0

    async def search(
        self,
        tenant: TenantContext,
        request: VectorSearchRequest,
    ) -> list[VectorSearchHit]:
        if request.tenant_id != tenant.tenant_id:
            return []
        allowed = set(request.document_ids)
        matched = [
            hit
            for hit in self.hits
            if hit.payload.tenant_id == tenant.tenant_id
            and (not allowed or hit.payload.document_id in allowed)
        ]
        return matched[: request.top_k]


class AssignedLexicalStore:
    def __init__(self, hits: list[tuple[ChunkBase, float]]) -> None:
        self.hits = hits

    async def search(
        self,
        tenant: TenantContext,
        *,
        query: str,
        top_k: int = 12,
        document_ids: list[UUID] | None = None,
        modalities: list[Modality] | None = None,
    ) -> list[LexicalHit]:
        del query, modalities
        allowed = set(document_ids or [])
        matched = [
            LexicalHit(chunk_id=chunk.chunk_id, score=score)
            for chunk, score in self.hits
            if chunk.tenant_id == tenant.tenant_id and (not allowed or chunk.document_id in allowed)
        ]
        return matched[:top_k]


def test_nested_rrf_preserves_a_retriever_score_of_0_80() -> None:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    strong = _chunk(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        text=KEPT,
        page_start=2,
        page_end=2,
    )
    weak = _chunk(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        text=REJECTED_CHILD,
        page_start=8,
        page_end=8,
    )
    other = _chunk(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Other list filler",
        page_start=3,
        page_end=3,
    )
    strong_evidence = chunk_to_evidence(strong, score=0.80, score_components={"dense": 0.80})
    weak_evidence = chunk_to_evidence(weak, score=0.05, score_components={"dense": 0.05})
    inner_strong = reciprocal_rank_fusion([[strong_evidence]])
    assert inner_strong[0].score == pytest.approx(1 / 61)
    assert inner_strong[0].score == pytest.approx(0.01639, abs=1e-5)
    assert _qualification(inner_strong[0].score_components) == pytest.approx([0.80])

    outer_strong = reciprocal_rank_fusion(
        [inner_strong, [chunk_to_evidence(other, score=0.40, score_components={"dense": 0.40})]]
    )
    kept = next(item for item in outer_strong if item.chunk_id == strong.chunk_id)
    assert kept.score == pytest.approx(1 / 61)
    assert _qualification(kept.score_components) == pytest.approx([0.80])
    assert retriever_score(kept) == pytest.approx(0.80)
    assert kept.score_components["rrf"] == pytest.approx(kept.score)

    inner_weak = reciprocal_rank_fusion([[weak_evidence]])
    outer_weak = reciprocal_rank_fusion(
        [inner_weak, [chunk_to_evidence(other, score=0.40, score_components={"dense": 0.40})]]
    )
    rejected = next(item for item in outer_weak if item.chunk_id == weak.chunk_id)
    assert _qualification(rejected.score_components) == pytest.approx([0.05])
    assert retriever_score(rejected) == pytest.approx(0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "question", "mode", "expected_modes"),
    _CASES,
    ids=[case[0] for case in _CASES],
)
async def test_query_modes_keep_0_80_and_drop_below_floor_evidence(
    label: str,
    question: str,
    mode: RetrievalMode,
    expected_modes: tuple[RetrievalMode, ...],
) -> None:
    del label
    tenant = TenantContext(tenant_id=new_id())
    other_tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    other_document_id = new_id()
    version_id = new_id()
    kept = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text=KEPT,
        page_start=2,
        page_end=2,
    )
    parent = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text=REJECTED_PARENT,
        page_start=8,
        page_end=11,
    )
    child = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text=REJECTED_CHILD,
        page_start=8,
        page_end=8,
        parent_chunk_id=parent.chunk_id,
    )
    neighbor = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text=REJECTED_NEIGHBOR,
        page_start=9,
        page_end=9,
        parent_chunk_id=parent.chunk_id,
    )
    outsider = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=other_document_id,
        version_id=version_id,
        text=OTHER_DOCUMENT,
        page_start=1,
        page_end=1,
    )
    chunks = InMemoryChunkLookupStore()
    await chunks.upsert(tenant, [kept, parent, child, neighbor, outsider])
    scored = [
        (kept, 0.80),
        (child, 0.05),
        (outsider, 0.99),
    ]
    service = RetrieveEvidenceService(
        embedding_model=FakeEmbeddingModel(),
        vector_store=AssignedScoreStore([_hit(chunk, score) for chunk, score in scored]),
        lexical_store=AssignedLexicalStore(scored),
        chunk_store=chunks,
    )
    request = RetrievalRequest(
        question=question,
        mode=mode,
        filters=RetrievalFilters(document_ids=[document_id]),
        top_k=8,
        rerank=False,
    )
    outcome = await service.retrieve(tenant, request)
    assert tuple(outcome.analysis.selected_modes) == expected_modes
    texts = [item.text for item in outcome.result.evidence]
    assert KEPT in texts
    assert REJECTED_CHILD not in texts
    assert REJECTED_PARENT not in texts
    assert REJECTED_NEIGHBOR not in texts
    assert OTHER_DOCUMENT not in texts
    kept_item = next(item for item in outcome.result.evidence if item.text == KEPT)
    assert kept_item.document_id == document_id
    assert retriever_score(kept_item) == pytest.approx(0.80)
    assert _qualification(kept_item.score_components) == pytest.approx([0.80])
    assert kept_item.score_components["rrf"] != pytest.approx(0.80)

    foreign = await service.retrieve(
        other_tenant,
        RetrievalRequest(
            question=question,
            mode=mode,
            filters=RetrievalFilters(document_ids=[document_id]),
            top_k=8,
            rerank=False,
        ),
    )
    assert foreign.result.evidence == []
    assert SELECTION_HAS_NO_SUPPORTING_EVIDENCE in foreign.result.warnings
