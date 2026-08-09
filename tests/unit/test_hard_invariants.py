"""Hard system invariant gate unit tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from enterprise_rag.domain.conversation.scope_expand import AWAITING_SCOPE_EXPAND
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.policies import (
    HARD_INVARIANTS,
    HardInvariant,
    HardInvariantGate,
    InvariantVerdict,
)
from enterprise_rag.domain.retrieval.models import RetrievedEvidence
from enterprise_rag.domain.tenant import TenantContext


def _evidence(text: str, *, score: float = 0.5, document_id: UUID | None = None) -> RetrievedEvidence:
    return RetrievedEvidence(
        chunk_id=new_id(),
        document_id=document_id or new_id(),
        document_version_id=new_id(),
        document_name="Doc.pdf",
        page_start=1,
        page_end=1,
        modality=Modality.TEXT,
        text=text,
        score=score,
        source_object_key="k",
    )


def test_all_six_hard_invariants_are_registered() -> None:
    assert len(HARD_INVARIANTS) == 6
    assert set(HARD_INVARIANTS) == set(HardInvariant)


def test_security_blocks_nil_tenant() -> None:
    gate = HardInvariantGate()
    verdict = InvariantVerdict()
    gate.enforce_security(TenantContext(tenant_id=UUID(int=0)), verdict)
    assert verdict.blocked
    assert "security_authorization_failed" in verdict.warnings
    assert HardInvariant.SECURITY_AUTHORIZATION.value not in verdict.enforced


def test_security_marks_authorized_tenant() -> None:
    gate = HardInvariantGate()
    verdict = InvariantVerdict()
    gate.enforce_security(TenantContext(tenant_id=new_id()), verdict)
    assert not verdict.blocked
    assert HardInvariant.SECURITY_AUTHORIZATION.value in verdict.enforced


def test_pinned_empty_evidence_blocks_with_expand_offer() -> None:
    gate = HardInvariantGate()
    verdict = InvariantVerdict()
    doc = uuid4()
    gate.enforce_evidence_sufficiency(
        question="What is the tinting pH?",
        evidence=[],
        pinned_document_ids=[doc],
        context_label="Alpha",
        expanded=False,
        verdict=verdict,
    )
    assert verdict.blocked
    assert verdict.block_answer is not None
    assert AWAITING_SCOPE_EXPAND in verdict.warnings
    assert HardInvariant.EVIDENCE_SUFFICIENCY.value in verdict.enforced


def test_empty_evidence_without_pin_does_not_block() -> None:
    gate = HardInvariantGate()
    verdict = InvariantVerdict()
    gate.enforce_evidence_sufficiency(
        question="What is the tinting pH?",
        evidence=[],
        pinned_document_ids=[],
        context_label="",
        expanded=False,
        verdict=verdict,
    )
    assert not verdict.blocked
    assert HardInvariant.EVIDENCE_SUFFICIENCY.value in verdict.enforced


def test_grounded_generation_softens_normative_overreach() -> None:
    gate = HardInvariantGate()
    verdict = InvariantVerdict()
    answer = gate.enforce_grounded_generation(
        question="What is the recommended use level?",
        answer="The recommended use level is 0.5%.",
        evidence=[
            _evidence(
                "Challenge test demonstrated efficacy at a use level of 0.5%."
            )
        ],
        cross_document_authorized=False,
        pinned_document_ids=[],
        verdict=verdict,
    )
    assert "recommended" not in answer.casefold() or "challenge" in answer.casefold() or "tested" in answer.casefold()
    assert HardInvariant.GROUNDED_GENERATION.value in verdict.enforced
    assert "claim_strength_overreach" in verdict.warnings


def test_citation_traceability_flags_missing_citations() -> None:
    gate = HardInvariantGate()
    verdict = InvariantVerdict()
    gate.enforce_citation_traceability(
        answer="Product Alpha has tinting pH 3.0 to 10.0.",
        citation_count=0,
        citation_warnings=[],
        verdict=verdict,
    )
    assert "answer_missing_citations" in verdict.warnings
    assert HardInvariant.CITATION_TRACEABILITY.value in verdict.enforced


def test_retrieval_scope_marks_expand_consent() -> None:
    gate = HardInvariantGate()
    verdict = InvariantVerdict()
    gate.enforce_retrieval_scope(
        pinned_document_ids=[],
        expanded=True,
        verdict=verdict,
    )
    assert "retrieval_scope_expanded_with_consent" in verdict.warnings
    assert HardInvariant.RETRIEVAL_SCOPE.value in verdict.enforced


@pytest.mark.asyncio
async def test_query_service_returns_enforced_invariants() -> None:
    """Smoke: successful query lists hard invariants on the response."""
    import json

    from enterprise_rag.application.chunking import EmbedChunksService
    from enterprise_rag.application.generation.generate_answer import GenerateAnswerService
    from enterprise_rag.application.generation.query import QueryDocumentsService
    from enterprise_rag.application.retrieval.retrieve import RetrieveEvidenceService
    from enterprise_rag.domain.chunks.models import ChunkBase, ChunkType
    from enterprise_rag.domain.ids import content_sha256_hex
    from enterprise_rag.domain.retrieval.enums import RetrievalMode
    from enterprise_rag.domain.retrieval.models import QueryRequest
    from enterprise_rag.infrastructure.models import FakeChatModel, FakeEmbeddingModel, FakeReranker
    from enterprise_rag.infrastructure.persistence.chunks import (
        InMemoryChunkLookupStore,
        InMemoryLexicalSearchStore,
    )
    from enterprise_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore

    tenant = TenantContext(tenant_id=new_id())
    doc_id = new_id()
    text = "Alpha tinting test performed over pH 3.0 to 10.0."
    chunk = ChunkBase(
        chunk_id=new_id(),
        tenant_id=tenant.tenant_id,
        document_id=doc_id,
        version_id=new_id(),
        modality=Modality.TEXT,
        chunk_type=ChunkType.TEXT,
        text=text,
        token_count=10,
        page_start=1,
        page_end=1,
        section_path=["Body"],
        source_object_keys=["x"],
        content_hash=content_sha256_hex(text),
        metadata={"document_name": "Alpha.pdf"},
    )
    store = InMemoryChunkLookupStore()
    await store.upsert(tenant, [chunk])
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    embedded = await EmbedChunksService(embedder).embed([chunk])
    await vectors.upsert(tenant, embedded.records)
    lexical = InMemoryLexicalSearchStore()
    await lexical.upsert(tenant, [chunk])

    def response_fn(_request) -> str:
        return json.dumps(
            {
                "answer": "Tinting was tested over pH 3.0 to 10.0 [C1].",
                "citation_ids": ["C1"],
            }
        )

    async def titles(_tenant: TenantContext) -> dict[UUID, str]:
        return {doc_id: "Alpha.pdf"}

    service = QueryDocumentsService(
        RetrieveEvidenceService(
            embedding_model=embedder,
            vector_store=vectors,
            chunk_store=store,
            lexical_store=lexical,
            reranker=FakeReranker(),
            document_names={doc_id: "Alpha.pdf"},
        ),
        GenerateAnswerService(FakeChatModel(response_fn=response_fn)),
        document_titles=titles,
    )
    result = await service.query(
        tenant,
        QueryRequest(question="What is the tinting pH range?", mode=RetrievalMode.NAIVE, top_k=3),
    )
    enforced = set(result.response.enforced_invariants)
    assert HardInvariant.SECURITY_AUTHORIZATION.value in enforced
    assert HardInvariant.RETRIEVAL_SCOPE.value in enforced
    assert HardInvariant.CONVERSATION_CONTEXT.value in enforced
    assert HardInvariant.EVIDENCE_SUFFICIENCY.value in enforced
    assert HardInvariant.GROUNDED_GENERATION.value in enforced
    assert HardInvariant.CITATION_TRACEABILITY.value in enforced
