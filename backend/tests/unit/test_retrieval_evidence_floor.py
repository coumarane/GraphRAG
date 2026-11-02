"""Retriever-score floor is applied before parent and neighbor expansion."""

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
from graph_rag.domain.conversation.scope_expand import build_scope_miss_message
from graph_rag.domain.generation.grounding_policy import (
    SELECTION_HAS_NO_SUPPORTING_EVIDENCE,
    at_or_above_evidence_floor,
)
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.policies.gate import HardInvariantGate, InvariantVerdict
from graph_rag.domain.retrieval import RetrievalFilters, RetrievalMode, RetrievalRequest
from graph_rag.domain.retrieval.assembly import chunk_to_evidence
from graph_rag.domain.retrieval.fusion import (
    apply_normalized_component,
    reciprocal_rank_fusion,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.models import FakeEmbeddingModel
from graph_rag.infrastructure.persistence.chunks import InMemoryChunkLookupStore


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


class AssignedScoreStore:
    """Return predetermined retriever scores. The query vector is ignored."""

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


def _evidence(chunk: ChunkBase, score: float):
    return chunk_to_evidence(chunk, score=score, score_components={"dense": score})


def test_one_item_minmax_and_rrf_do_not_pass_the_floor() -> None:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    weak = _chunk(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Weak assigned score stays below the floor.",
        page_start=1,
        page_end=1,
    )
    strong = _chunk(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Strong assigned score stays available after fusion.",
        page_start=2,
        page_end=2,
    )
    normalized = apply_normalized_component(
        [_evidence(weak, 0.05)],
        component_name="normalized",
    )
    assert normalized[0].score_components["normalized"] == 1.0
    assert not at_or_above_evidence_floor(normalized[0])

    fused_weak = reciprocal_rank_fusion([[_evidence(weak, 0.05)]])
    assert fused_weak[0].score < 0.12
    assert fused_weak[0].score_components["source_score_0"] == 0.05
    assert not at_or_above_evidence_floor(fused_weak[0])

    fused_strong = reciprocal_rank_fusion([[_evidence(strong, 0.8)]])
    assert fused_strong[0].score < 0.12
    assert at_or_above_evidence_floor(fused_strong[0])


@pytest.mark.asyncio
async def test_floor_drops_weak_hits_before_parent_expansion() -> None:
    tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    version_id = new_id()
    parent = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="ParentSpanShouldNotAppear",
        page_start=1,
        page_end=4,
    )
    child = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="BelowFloorChildOnly",
        page_start=2,
        page_end=2,
        parent_chunk_id=parent.chunk_id,
    )
    chunks = InMemoryChunkLookupStore()
    await chunks.upsert(tenant, [parent, child])
    service = RetrieveEvidenceService(
        embedding_model=FakeEmbeddingModel(),
        vector_store=AssignedScoreStore([_hit(child, 0.05)]),
        chunk_store=chunks,
    )
    outcome = await service.retrieve(
        tenant,
        RetrievalRequest(
            question="How should an overnight serum be kept?",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[document_id]),
            top_k=8,
            rerank=False,
        ),
    )
    texts = [item.text for item in outcome.result.evidence]
    assert texts == []
    assert SELECTION_HAS_NO_SUPPORTING_EVIDENCE in outcome.result.warnings
    assert "ParentSpanShouldNotAppear" not in texts


@pytest.mark.asyncio
async def test_above_floor_paraphrase_keeps_child_and_parent_pages() -> None:
    tenant = TenantContext(tenant_id=new_id())
    other = TenantContext(tenant_id=new_id())
    document_id = new_id()
    other_document_id = new_id()
    version_id = new_id()
    parent = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Parent pages one through four of the serum note.",
        page_start=1,
        page_end=4,
    )
    child = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Keep the ceramide serum between 15 and 25 degrees.",
        page_start=2,
        page_end=2,
        parent_chunk_id=parent.chunk_id,
    )
    other_sentence = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=other_document_id,
        version_id=version_id,
        text="OtherDocumentSentenceAbsent",
        page_start=1,
        page_end=1,
    )
    chunks = InMemoryChunkLookupStore()
    await chunks.upsert(tenant, [parent, child, other_sentence])
    service = RetrieveEvidenceService(
        embedding_model=FakeEmbeddingModel(),
        vector_store=AssignedScoreStore([_hit(child, 0.42), _hit(other_sentence, 0.04)]),
        chunk_store=chunks,
    )
    question = "How should the serum be stored overnight?"
    outcome = await service.retrieve(
        tenant,
        RetrievalRequest(
            question=question,
            mode=RetrievalMode.NAIVE,
            top_k=8,
            rerank=False,
        ),
    )
    by_id = {item.chunk_id: item for item in outcome.result.evidence}
    assert child.chunk_id in by_id
    assert by_id[child.chunk_id].page_start == 2
    assert by_id[child.chunk_id].page_end == 2
    assert question not in by_id[child.chunk_id].text
    assert parent.chunk_id in by_id
    assert by_id[parent.chunk_id].page_start == 1
    assert by_id[parent.chunk_id].page_end == 4
    assert "OtherDocumentSentenceAbsent" not in {item.text for item in outcome.result.evidence}

    foreign = await service.retrieve(
        other,
        RetrievalRequest(
            question=question,
            mode=RetrievalMode.NAIVE,
            top_k=8,
            rerank=False,
        ),
    )
    assert foreign.result.evidence == []
    assert SELECTION_HAS_NO_SUPPORTING_EVIDENCE in foreign.result.warnings


def test_pinned_empty_evidence_keeps_the_scope_message_and_adds_the_warning() -> None:
    gate = HardInvariantGate()
    verdict = InvariantVerdict()
    document_id = new_id()
    gate.enforce_evidence_sufficiency(
        question="Where is the overnight storage note?",
        evidence=[],
        pinned_document_ids=[document_id],
        context_label="the serum",
        expanded=False,
        verdict=verdict,
    )
    assert SELECTION_HAS_NO_SUPPORTING_EVIDENCE in verdict.warnings
    assert verdict.blocked is True
    assert verdict.block_answer == build_scope_miss_message("the serum")
