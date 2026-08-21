"""Conversation scope + expand consent integration tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from enterprise_rag.application.chunking import EmbedChunksService
from enterprise_rag.application.generation.generate_answer import GenerateAnswerService
from enterprise_rag.application.generation.query import QueryDocumentsService
from enterprise_rag.application.retrieval.retrieve import RetrieveEvidenceService
from enterprise_rag.domain.chunks.models import ChunkBase, ChunkType
from enterprise_rag.domain.conversation.scope_expand import (
    AWAITING_SCOPE_EXPAND,
    DOCUMENT_SCOPE_EXPANDED,
)
from enterprise_rag.domain.ids import content_sha256_hex, new_id
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.retrieval.enums import RetrievalMode
from enterprise_rag.domain.retrieval.models import QueryRequest, RetrievalFilters
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.models import FakeChatModel, FakeEmbeddingModel, FakeReranker
from enterprise_rag.infrastructure.persistence.chunks import (
    InMemoryChunkLookupStore,
    InMemoryLexicalSearchStore,
)
from enterprise_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore


def _hash(text: str) -> str:
    return content_sha256_hex(text)


def _chunk(
    *,
    tenant_id,
    document_id,
    version_id,
    text: str,
    name: str,
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
        source_object_keys=["x"],
        content_hash=_hash(text + name),
        metadata={"document_name": name},
    )


@pytest.mark.asyncio
async def test_followup_stays_in_pinned_context_not_other_doc() -> None:
    tenant = TenantContext(tenant_id=new_id())
    doc_a = uuid4()
    doc_b = uuid4()
    ver_a = new_id()
    ver_b = new_id()
    chunk_a = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=doc_a,
        version_id=ver_a,
        text="Product Alpha tinting test performed over pH 3.0 to 10.0.",
        name="Alpha.pdf",
    )
    chunk_b = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=doc_b,
        version_id=ver_b,
        text="Product Beta tinting test performed over pH 4 to 8 only.",
        name="Beta.pdf",
    )

    store = InMemoryChunkLookupStore()
    await store.upsert(tenant, [chunk_a, chunk_b])
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    embedded = await EmbedChunksService(embedder).embed([chunk_a, chunk_b])
    await vectors.upsert(tenant, embedded.records)
    lexical = InMemoryLexicalSearchStore()
    await lexical.upsert(tenant, [chunk_a, chunk_b])

    def response_fn(request) -> str:
        import json

        return json.dumps(
            {
                "answer": "Tinting for Alpha was tested over pH 3.0 to 10.0 [C1].",
                "citation_ids": ["C1"],
            }
        )

    titles = {doc_a: "Alpha.pdf", doc_b: "Beta.pdf"}

    async def title_provider(_tenant: TenantContext):
        return titles

    service = QueryDocumentsService(
        RetrieveEvidenceService(
            embedding_model=embedder,
            vector_store=vectors,
            chunk_store=store,
            lexical_store=lexical,
            reranker=FakeReranker(),
            document_names=titles,
        ),
        GenerateAnswerService(FakeChatModel(response_fn=response_fn)),
        document_titles=title_provider,
    )

    # Follow-up with sticky pin to Alpha only.
    outcome = await service.query(
        tenant,
        QueryRequest(
            question="Over which pH range was the tinting test performed?",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[doc_a]),
            conversation_history=[
                {"role": "user", "content": "Tell me about Alpha"},
                {"role": "assistant", "content": "Alpha is an antimicrobial."},
            ],
            rerank=False,
        ),
    )
    cites = outcome.response.citations
    assert cites
    assert all(c.document_id == doc_a for c in cites)
    assert "Beta" not in outcome.response.answer


@pytest.mark.asyncio
async def test_first_turn_naming_one_product_pins_before_retrieval() -> None:
    """Regression for a real production bug: a fresh, first-turn question
    ("What is EMULGEN 2020G composition?", no conversation_history) returned
    a completely unrelated product's ingredient table. Root cause: retrieval
    only pinned document_ids for follow-ups or detected context switches —
    "first turn may search openly" — so an explicitly-named product on turn
    one got no scoping at all, letting a longer/richer unrelated document
    outrank the short one it actually named. The fix pins on turn one too,
    but only when the named entity matches exactly one document (ambiguous
    or unmatched entities still search openly, unchanged).
    """
    tenant = TenantContext(tenant_id=new_id())
    doc_gamma = uuid4()
    doc_delta = uuid4()
    ver_gamma = new_id()
    ver_delta = new_id()
    chunk_gamma = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=doc_gamma,
        version_id=ver_gamma,
        text="GAMMA 100 INCI: OCTYLDODECETH-20, 100%.",
        name="GAMMA 100-SPEC.pdf",
    )
    chunk_delta = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=doc_delta,
        version_id=ver_delta,
        text="DELTA composition: Butylene Glycol 6.0%, Glycerin 4.0%, Water to 100%.",
        name="DELTA SERIES.pdf",
    )

    store = InMemoryChunkLookupStore()
    await store.upsert(tenant, [chunk_gamma, chunk_delta])
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    embedded = await EmbedChunksService(embedder).embed([chunk_gamma, chunk_delta])
    await vectors.upsert(tenant, embedded.records)
    lexical = InMemoryLexicalSearchStore()
    await lexical.upsert(tenant, [chunk_gamma, chunk_delta])

    def response_fn(request) -> str:
        import json

        return json.dumps(
            {
                "answer": "GAMMA 100 is OCTYLDODECETH-20, 100% [C1].",
                "citation_ids": ["C1"],
            }
        )

    titles = {doc_gamma: "GAMMA 100-SPEC.pdf", doc_delta: "DELTA SERIES.pdf"}

    async def title_provider(_tenant: TenantContext):
        return titles

    service = QueryDocumentsService(
        RetrieveEvidenceService(
            embedding_model=embedder,
            vector_store=vectors,
            chunk_store=store,
            lexical_store=lexical,
            reranker=FakeReranker(),
            document_names=titles,
        ),
        GenerateAnswerService(FakeChatModel(response_fn=response_fn)),
        document_titles=title_provider,
    )

    # First turn: no conversation_history, no pre-set document_ids filter —
    # only the product name in the question itself to go on.
    outcome = await service.query(
        tenant,
        QueryRequest(
            question="What is GAMMA 100 composition?",
            mode=RetrievalMode.NAIVE,
            top_k=5,
            rerank=False,
        ),
    )
    cites = outcome.response.citations
    assert cites
    assert all(c.document_id == doc_gamma for c in cites)
    assert "DELTA" not in outcome.response.answer


@pytest.mark.asyncio
async def test_scope_miss_then_yes_expands() -> None:
    tenant = TenantContext(tenant_id=new_id())
    doc_a = uuid4()
    doc_b = uuid4()
    chunk_b = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=doc_b,
        version_id=new_id(),
        text="Manufacturer of Product Zeta is Contoso Labs.",
        name="Zeta.pdf",
    )
    store = InMemoryChunkLookupStore()
    await store.upsert(tenant, [chunk_b])
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    embedded = await EmbedChunksService(embedder).embed([chunk_b])
    await vectors.upsert(tenant, embedded.records)
    lexical = InMemoryLexicalSearchStore()
    await lexical.upsert(tenant, [chunk_b])

    def response_fn(request) -> str:
        import json

        return json.dumps(
            {
                "answer": "Manufacturer of Product Zeta is Contoso Labs [C1].",
                "citation_ids": ["C1"],
            }
        )

    async def titles(_t):
        return {doc_a: "Alpha.pdf", doc_b: "Zeta.pdf"}

    service = QueryDocumentsService(
        RetrieveEvidenceService(
            embedding_model=embedder,
            vector_store=vectors,
            chunk_store=store,
            lexical_store=lexical,
            reranker=FakeReranker(),
            document_names={doc_b: "Zeta.pdf"},
        ),
        GenerateAnswerService(FakeChatModel(response_fn=response_fn)),
        document_titles=titles,
    )

    miss = await service.query(
        tenant,
        QueryRequest(
            question="Who manufactures Product Zeta?",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[doc_a]),
            rerank=False,
        ),
    )
    assert AWAITING_SCOPE_EXPAND in miss.response.warnings
    assert "conversation context" in miss.response.answer.casefold()

    expanded = await service.query(
        tenant,
        QueryRequest(
            question="yes",
            mode=RetrievalMode.NAIVE,
            filters=RetrievalFilters(document_ids=[doc_a]),
            conversation_history=[
                {"role": "user", "content": "Who manufactures Product Zeta?"},
                {"role": "assistant", "content": miss.response.answer},
            ],
            expand_document_scope=True,
            rerank=False,
        ),
    )
    assert DOCUMENT_SCOPE_EXPANDED in expanded.response.warnings
    assert "Contoso" in expanded.response.answer
