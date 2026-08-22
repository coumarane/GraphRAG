"""QueryDocumentsService document-scope miss behavior."""

from __future__ import annotations

from uuid import uuid4

import pytest

from graph_rag.application.generation.generate_answer import GenerateAnswerService
from graph_rag.application.generation.query import QueryDocumentsService
from graph_rag.application.retrieval.retrieve import RetrieveEvidenceService
from graph_rag.domain.conversation.scope_expand import AWAITING_SCOPE_EXPAND
from graph_rag.domain.ids import new_id
from graph_rag.domain.retrieval.enums import RetrievalMode
from graph_rag.domain.retrieval.models import QueryRequest, RetrievalFilters
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.models import FakeChatModel, FakeEmbeddingModel, FakeReranker
from graph_rag.infrastructure.persistence.chunks import (
    InMemoryChunkLookupStore,
    InMemoryLexicalSearchStore,
)
from graph_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore


@pytest.mark.asyncio
async def test_scoped_empty_evidence_offers_expand_not_corpus_search() -> None:
    tenant = TenantContext(tenant_id=new_id())
    doc_id = uuid4()

    async def titles(_tenant: TenantContext) -> dict:
        return {doc_id: "【Presentation】 SY-KNP.pdf"}

    retrieve = RetrieveEvidenceService(
        embedding_model=FakeEmbeddingModel(),
        vector_store=InMemoryChunkVectorStore(),
        chunk_store=InMemoryChunkLookupStore(),
        lexical_store=InMemoryLexicalSearchStore(),
        reranker=FakeReranker(),
    )
    # Empty vector store needs a collection size for naive branch; ensure collection.
    await retrieve._vectors.ensure_collection(vector_size=2)  # type: ignore[attr-defined]

    service = QueryDocumentsService(
        retrieve,
        GenerateAnswerService(FakeChatModel()),
        document_titles=titles,
    )
    outcome = await service.query(
        tenant,
        QueryRequest(
            question="Who manufactures SY-KNP?",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[doc_id]),
            rerank=False,
        ),
    )
    assert AWAITING_SCOPE_EXPAND in outcome.response.warnings
    assert "SY-KNP" in outcome.response.answer
    assert "conversation context" in outcome.response.answer.casefold()
    assert "yes" in outcome.response.answer.casefold()
    assert outcome.generation is None
