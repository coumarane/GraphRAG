"""Claim-strength fidelity: tested levels ≠ recommendations."""

from __future__ import annotations

from graph_rag.application.generation.prompts import build_answer_messages
from graph_rag.domain.citations.registry import CitationRegistry
from graph_rag.domain.generation.claim_fidelity import (
    CLAIM_STRENGTH_OVERREACH,
    build_claim_fidelity_hint,
    detect_claim_strength_overreach,
    question_asks_normative_value,
)
from graph_rag.domain.ids import new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.retrieval.enums import RetrievalMode
from graph_rag.domain.retrieval.models import RetrievedEvidence
from graph_rag.domain.tenant import TenantContext


def _evidence(text: str) -> RetrievedEvidence:
    return RetrievedEvidence(
        chunk_id=new_id(),
        document_id=new_id(),
        document_version_id=new_id(),
        document_name="SY-KNP.pdf",
        page_start=5,
        page_end=5,
        section_path=["Page 5"],
        modality=Modality.TEXT,
        source_object_key="x",
        text=text,
        score=0.9,
    )


def test_question_asks_recommended_use_level() -> None:
    assert question_asks_normative_value(
        "What is the recommended use level in a finished formula?"
    )


def test_challenge_test_is_not_normative_evidence() -> None:
    texts = [
        "Challenge test in toner (Mold fungi) 0.5% KNP "
        "SY-KNP showing antimicrobial activity equal to synthetic preservatives"
    ]
    hint = build_claim_fidelity_hint(
        "What is the recommended use level in a finished formula?",
        texts,
    )
    assert hint is not None
    assert "Do NOT say" in hint or "recommended use level" in hint


def test_explicit_recommendation_skips_hint() -> None:
    texts = ["Recommended use level: 0.3–1.0% in finished formulations."]
    assert (
        build_claim_fidelity_hint(
            "What is the recommended use level?",
            texts,
        )
        is None
    )


def test_detect_overreach() -> None:
    texts = ["Challenge test in cream 0.5% KNP"]
    assert detect_claim_strength_overreach(
        "What is the recommended use level in a finished formula?",
        "The recommended use level in a finished formula is 0.5%.",
        texts,
    )
    assert not detect_claim_strength_overreach(
        "What is the recommended use level in a finished formula?",
        "0.5% KNP was used in challenge tests; no explicit recommended use level was found.",
        texts,
    )


def test_build_answer_messages_includes_fidelity_hint() -> None:
    tenant = TenantContext(tenant_id=new_id())
    evidence = [
        _evidence(
            "Challenge test in toner 0.5% KNP showing antimicrobial activity"
        )
    ]
    registry = CitationRegistry(tenant, evidence)
    messages = build_answer_messages(
        question="What is the recommended use level in a finished formula?",
        mode=RetrievalMode.HYBRID,
        registry=registry,
        evidence=evidence,
    )
    user = messages[1].content
    assert "CLAIM FIDELITY" in user
    assert CLAIM_STRENGTH_OVERREACH  # imported constant exists
