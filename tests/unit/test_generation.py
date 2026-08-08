"""Grounded generation, citation registry and validation tests."""

from __future__ import annotations

import json

import pytest

from enterprise_rag.application.chunking import EmbedChunksService
from enterprise_rag.application.generation import (
    GenerateAnswerService,
    QueryDocumentsService,
)
from enterprise_rag.application.retrieval import RetrieveEvidenceService
from enterprise_rag.domain.chunks.models import ChunkBase, ChunkType
from enterprise_rag.domain.citations import (
    CitationRegistry,
    extract_citation_ids,
    parse_generation_text,
    remap_graph_path_citations,
    validate_citations,
)
from enterprise_rag.domain.ids import content_sha256_hex, new_id
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.models.contracts import GenerationRequest
from enterprise_rag.domain.retrieval import (
    GraphPath,
    QueryRequest,
    RetrievalMode,
    RetrievalResult,
    RetrievedEvidence,
)
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.models import FakeChatModel, FakeEmbeddingModel
from enterprise_rag.infrastructure.persistence.chunks import InMemoryChunkLookupStore
from enterprise_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore
from enterprise_rag.shared.exceptions import CitationValidationError


def _hash(text: str) -> str:
    return content_sha256_hex(text)


def _evidence(
    *,
    tenant_id,
    text: str,
    document_name: str = "spec.pdf",
) -> RetrievedEvidence:
    document_id = new_id()
    return RetrievedEvidence(
        chunk_id=new_id(),
        document_id=document_id,
        document_version_id=new_id(),
        document_name=document_name,
        page_start=2,
        page_end=2,
        section_path=["Physical Properties", "Viscosity"],
        element_id=new_id(),
        modality=Modality.TEXT,
        source_object_key="tenant/doc/v1/original.pdf",
        text=text,
        score=0.9,
        score_components={"dense": 0.9},
    )


def test_registry_assigns_stable_citation_ids() -> None:
    tenant = TenantContext(tenant_id=new_id())
    e1 = _evidence(tenant_id=tenant.tenant_id, text="Viscosity decreases with heat.")
    e2 = _evidence(tenant_id=tenant.tenant_id, text="Store below 25C.")
    registry = CitationRegistry(tenant, [e1, e2])
    assert registry.ids() == ["C1", "C2"]
    assert registry.get("C1") is not None
    assert registry.citation_id_for_chunk(e1.chunk_id) == "C1"
    assert "[C1]" in registry.prompt_block()


def test_validate_citations_strips_unknown_ids() -> None:
    tenant = TenantContext(tenant_id=new_id())
    evidence = _evidence(tenant_id=tenant.tenant_id, text="Silicone oil is stable.")
    registry = CitationRegistry(tenant, [evidence])
    result = validate_citations(
        tenant=tenant,
        answer="Silicone oil is stable [C1] and also magical [C99].",
        registry=registry,
        claimed_ids=["C1", "C99"],
        strict=False,
    )
    assert result.cited_ids == ["C1"]
    assert "C99" in result.unknown_ids
    assert "[C99]" not in result.answer
    assert "[C1]" in result.answer
    assert len(result.citations) == 1


def test_validate_numeric_grounding_flags_column_misread() -> None:
    from enterprise_rag.domain.citations import validate_numeric_grounding

    tenant = TenantContext(tenant_id=new_id())
    evidence = _evidence(
        tenant_id=tenant.tenant_id,
        text="High purity glass Component Regular Glass TA GLASS\nPb 4-7 N.D.\nCr 5> N.D.\nSb 5> N.D.",
    )
    registry = CitationRegistry(tenant, [evidence])
    result = validate_citations(
        tenant=tenant,
        answer=(
            "For TA glass:\n"
            "- Lead (Pb): Not detected (N.D.) [C1]\n"
            "- Chromium (Cr): Less than 5 ppm [C1]\n"
        ),
        registry=registry,
        claimed_ids=["C1"],
        strict=False,
    )
    assert any(w.startswith("ungrounded_numeric:chromium") for w in result.warnings)
    assert result.valid is False
    # Supported N.D. claim should not warn for lead.
    assert not any(w.startswith("ungrounded_numeric:lead") for w in result.warnings)
    assert validate_numeric_grounding(answer=result.answer, citations=result.citations)


def test_validate_citations_strict_raises() -> None:
    tenant = TenantContext(tenant_id=new_id())
    evidence = _evidence(tenant_id=tenant.tenant_id, text="fact")
    registry = CitationRegistry(tenant, [evidence])
    with pytest.raises(CitationValidationError):
        validate_citations(
            tenant=tenant,
            answer="Invented claim [C9]",
            registry=registry,
            strict=True,
        )


def test_parse_structured_generation() -> None:
    payload = {
        "answer": "Viscosity falls with temperature [C1].",
        "citation_ids": ["C1"],
        "warnings": ["low_confidence_axis_labels"],
    }
    parsed = parse_generation_text(json.dumps(payload))
    assert parsed.structured
    assert parsed.citation_ids == ["C1"]
    assert extract_citation_ids(parsed.answer) == ["C1"]


def test_parse_generation_coerces_string_warnings() -> None:
    payload = {
        "answer": "Pb is N.D. [C1].",
        "citation_ids": ["C1"],
        "warnings": "Units not specified in the source.",
    }
    parsed = parse_generation_text(json.dumps(payload))
    assert parsed.structured
    assert parsed.answer == "Pb is N.D. [C1]."
    assert parsed.warnings == ["Units not specified in the source."]
    assert "{" not in parsed.answer


def test_remap_graph_paths_to_citation_ids() -> None:
    tenant = TenantContext(tenant_id=new_id())
    evidence = _evidence(tenant_id=tenant.tenant_id, text="claim text")
    registry = CitationRegistry(tenant, [evidence])
    paths = [
        GraphPath(
            nodes=["silicone oil", "temperature"],
            relationships=["DECREASES_WITH"],
            supporting_citations=[str(evidence.chunk_id)],
        )
    ]
    remapped = remap_graph_path_citations(paths, registry)
    assert remapped[0].supporting_citations == ["C1"]


@pytest.mark.asyncio
async def test_generate_answer_validates_and_retries() -> None:
    tenant = TenantContext(tenant_id=new_id())
    evidence = _evidence(
        tenant_id=tenant.tenant_id,
        text="Measured viscosity declined with temperature.",
    )
    retrieval = RetrievalResult(
        mode=RetrievalMode.NAIVE,
        retrieval_trace_id=new_id(),
        evidence=[evidence],
        graph_paths=[
            GraphPath(
                nodes=["viscosity", "temperature"],
                relationships=["DECREASES_WITH"],
                supporting_citations=[str(evidence.chunk_id)],
            )
        ],
    )

    calls = {"n": 0}

    def response_fn(request: GenerationRequest) -> str:
        calls["n"] += 1
        allowed = request.metadata.get("allowed_citation_ids") or []
        if calls["n"] == 1:
            return json.dumps(
                {
                    "answer": "Wrong citation [C99].",
                    "citation_ids": ["C99"],
                }
            )
        return json.dumps(
            {
                "answer": "Viscosity declined with temperature [C1].",
                "citation_ids": list(allowed)[:1] or ["C1"],
            }
        )

    chat = FakeChatModel(response_fn=response_fn)
    service = GenerateAnswerService(chat, max_retries=1)
    result = await service.generate(
        tenant,
        question="What happens to viscosity with temperature?",
        retrieval=retrieval,
    )
    assert result.retried
    assert result.response.citations
    assert result.response.citations[0].citation_id == "C1"
    assert "[C1]" in result.response.answer
    assert "[C99]" not in result.response.answer
    assert result.response.graph_paths[0].supporting_citations == ["C1"]
    assert result.response.retrieval_mode is RetrievalMode.NAIVE
    assert len(chat.calls) == 2


@pytest.mark.asyncio
async def test_generate_answer_handles_empty_evidence() -> None:
    tenant = TenantContext(tenant_id=new_id())
    retrieval = RetrievalResult(
        mode=RetrievalMode.HYBRID,
        retrieval_trace_id=new_id(),
        evidence=[],
    )
    service = GenerateAnswerService(FakeChatModel(text="should not be used"))
    result = await service.generate(
        tenant,
        question="Anything?",
        retrieval=retrieval,
    )
    assert result.response.citations == []
    assert "weak_evidence" in result.response.warnings
    assert result.response.answer


@pytest.mark.asyncio
async def test_query_documents_end_to_end() -> None:
    tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    version_id = new_id()
    chunk = ChunkBase(
        chunk_id=new_id(),
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        modality=Modality.TEXT,
        chunk_type=ChunkType.TEXT,
        text="Storage temperature should remain below 25 Celsius.",
        token_count=8,
        page_start=1,
        page_end=1,
        section_path=["Storage"],
        source_object_keys=["tenant/doc/v1/original.pdf"],
        content_hash=_hash("storage"),
        metadata={"document_name": "spec.pdf"},
    )
    chunk_store = InMemoryChunkLookupStore()
    await chunk_store.upsert(tenant, [chunk])
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    await vectors.ensure_collection(vector_size=2)
    await vectors.upsert(tenant, (await EmbedChunksService(embedder).embed([chunk])).records)

    def response_fn(request: GenerationRequest) -> str:
        allowed = request.metadata.get("allowed_citation_ids") or ["C1"]
        citation_id = allowed[0] if isinstance(allowed, list) and allowed else "C1"
        return json.dumps(
            {
                "answer": f"Keep storage below 25C [{citation_id}].",
                "citation_ids": [citation_id],
            }
        )

    retrieve = RetrieveEvidenceService(
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=chunk_store,
        document_names={document_id: "spec.pdf"},
    )
    generate = GenerateAnswerService(FakeChatModel(response_fn=response_fn))
    query = QueryDocumentsService(retrieve, generate)
    outcome = await query.query(
        tenant,
        QueryRequest(
            question="What is the recommended storage temperature?",
            mode=RetrievalMode.NAIVE,
            top_k=3,
            rerank=False,
            include_graph_paths=False,
        ),
    )
    assert outcome.response.citations
    assert outcome.response.retrieval_trace_id
    assert outcome.response.answer
    assert outcome.retrieval.result.evidence
