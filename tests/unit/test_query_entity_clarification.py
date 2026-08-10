"""QueryDocumentsService entity-clarification resume behavior."""

from __future__ import annotations

from uuid import uuid4

import pytest

from enterprise_rag.application.generation.generate_answer import GenerateAnswerService
from enterprise_rag.application.generation.query import QueryDocumentsService
from enterprise_rag.application.retrieval.retrieve import RetrieveEvidenceService
from enterprise_rag.domain.conversation.entity_clarification import (
    AWAITING_ENTITY_CLARIFICATION,
)
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.retrieval.enums import RetrievalMode
from enterprise_rag.domain.retrieval.models import QueryRequest, RetrievalFilters
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.models import FakeChatModel, FakeEmbeddingModel, FakeReranker
from enterprise_rag.infrastructure.persistence.chunks import (
    InMemoryChunkLookupStore,
    InMemoryLexicalSearchStore,
)
from enterprise_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore


def _service(titles_map: dict) -> QueryDocumentsService:
    async def titles(_tenant: TenantContext) -> dict:
        return titles_map

    retrieve = RetrieveEvidenceService(
        embedding_model=FakeEmbeddingModel(),
        vector_store=InMemoryChunkVectorStore(),
        chunk_store=InMemoryChunkLookupStore(),
        lexical_store=InMemoryLexicalSearchStore(),
        reranker=FakeReranker(),
    )
    return QueryDocumentsService(
        retrieve,
        GenerateAnswerService(FakeChatModel()),
        document_titles=titles,
    )


@pytest.mark.asyncio
async def test_clarification_reply_resumes_pending_question() -> None:
    tenant = TenantContext(tenant_id=new_id())
    doc_id = uuid4()
    service = _service({doc_id: "【Presentation】 SY-KNP.pdf"})
    await service._retrieve._vectors.ensure_collection(vector_size=2)  # type: ignore[attr-defined]

    pending = "How many red pins are on the contracted farmer map?"
    outcome = await service.query(
        tenant,
        QueryRequest(
            question="SY-KNP",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[]),
            conversation_history=[
                {"role": "user", "content": pending},
                {
                    "role": "assistant",
                    "content": "Which entity are you referring to: SY-KNP or Who?",
                },
            ],
            rerank=False,
        ),
    )
    assert "entity_clarification_resumed" in outcome.response.warnings
    assert AWAITING_ENTITY_CLARIFICATION not in outcome.response.warnings
    assert outcome.context is not None
    resumed = f"{outcome.context.query} {outcome.context.resolved_query}"
    assert "red pins" in resumed.casefold()
    assert "sy-knp" in resumed.casefold()
    # Must not short-circuit as a fresh "tell me about SY-KNP" clarification answer.
    assert "which entity are you referring to" not in outcome.response.answer.casefold()


@pytest.mark.asyncio
async def test_pinned_document_skips_entity_clarification() -> None:
    tenant = TenantContext(tenant_id=new_id())
    doc_id = uuid4()
    service = _service({doc_id: "【Presentation】 SY-KNP.pdf"})
    await service._retrieve._vectors.ensure_collection(vector_size=2)  # type: ignore[attr-defined]

    outcome = await service.query(
        tenant,
        QueryRequest(
            question="How many red pins are on the map?",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[doc_id]),
            conversation_history=[
                {"role": "user", "content": "Compare SY-KNP and Who for MIC"},
                {
                    "role": "assistant",
                    "content": "SY-KNP has lower MIC than the other option [C1].",
                },
            ],
            rerank=False,
        ),
    )
    assert AWAITING_ENTITY_CLARIFICATION not in outcome.response.warnings
    assert "which entity are you referring to" not in outcome.response.answer.casefold()


@pytest.mark.asyncio
async def test_active_context_includes_document_ids_from_entity_titles() -> None:
    tenant = TenantContext(tenant_id=new_id())
    doc_id = uuid4()
    service = _service({doc_id: "【Presentation】 SY-KNP.pdf"})
    await service._retrieve._vectors.ensure_collection(vector_size=2)  # type: ignore[attr-defined]

    outcome = await service.query(
        tenant,
        QueryRequest(
            question="Who manufactures SY-KNP?",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[]),
            rerank=False,
        ),
    )
    ctx = outcome.response.active_conversation_context
    assert ctx is not None
    assert "SY-KNP" in str(ctx.get("label") or "")
    # Even with weak/empty evidence, entity→title match must pin the doc for follow-ups.
    assert [str(doc_id)] == [str(item) for item in (ctx.get("document_ids") or [])]


@pytest.mark.asyncio
async def test_followup_with_named_entity_does_not_ask_which_entity() -> None:
    tenant = TenantContext(tenant_id=new_id())
    doc_id = uuid4()
    service = _service({doc_id: "【Presentation】 SY-KNP.pdf"})
    await service._retrieve._vectors.ensure_collection(vector_size=2)  # type: ignore[attr-defined]

    outcome = await service.query(
        tenant,
        QueryRequest(
            question=(
                "On the contract-farming map for A. capillaris / SY-KNP: "
                "how many farmer locations are shown as pins in Japan, "
                "and does that match the text about contracted farmers?"
            ),
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[doc_id]),
            conversation_history=[
                {"role": "user", "content": "Who manufactures SY-KNP?"},
                {
                    "role": "assistant",
                    "content": (
                        "For SY-KNP: evidence does not directly name a manufacturer. "
                        "BNB CHEM appears in the presentation."
                    ),
                },
            ],
            rerank=False,
        ),
    )
    assert AWAITING_ENTITY_CLARIFICATION not in outcome.response.warnings
    assert "which entity are you referring to" not in outcome.response.answer.casefold()
    assert "Who?" not in outcome.response.answer
