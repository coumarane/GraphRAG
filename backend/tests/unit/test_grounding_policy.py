"""Grounding policy: sufficiency, conflicts, graph-path hygiene."""

from __future__ import annotations

from uuid import uuid4

from graph_rag.application.generation.prompts import SYSTEM_PROMPT, build_answer_messages
from graph_rag.domain.citations.registry import CitationRegistry
from graph_rag.domain.generation.grounding_policy import (
    CONFLICTING_EVIDENCE,
    EvidenceSufficiency,
    assess_evidence,
    detect_numeric_conflicts,
    filter_grounded_graph_paths,
)
from graph_rag.domain.ids import new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.retrieval.enums import RetrievalMode
from graph_rag.domain.retrieval.models import GraphPath, RetrievedEvidence
from graph_rag.domain.tenant import TenantContext


def _ev(text: str, *, name: str, score: float = 0.8) -> RetrievedEvidence:
    return RetrievedEvidence(
        chunk_id=new_id(),
        document_id=new_id(),
        document_version_id=new_id(),
        document_name=name,
        page_start=1,
        page_end=1,
        section_path=["Results"],
        modality=Modality.TEXT,
        source_object_key="x",
        text=text,
        score=score,
    )


def test_system_prompt_has_no_brand_hardcodes() -> None:
    lowered = SYSTEM_PROMPT.casefold()
    for brand in ("metashine", "silkyflake", "natutect", "mar'vina", "byk-mac"):
        assert brand not in lowered


def test_assess_empty_evidence_insufficient() -> None:
    assessment = assess_evidence(question="What is Cd?", evidence=[])
    assert assessment.sufficiency is EvidenceSufficiency.INSUFFICIENT


def test_assess_normative_ask_with_challenge_is_partial() -> None:
    evidence = [
        _ev(
            "Challenge test in toner 0.5% KNP showing antimicrobial activity",
            name="a.pdf",
        )
    ]
    assessment = assess_evidence(
        question="What is the recommended use level in a finished formula?",
        evidence=evidence,
    )
    assert assessment.sufficiency is EvidenceSufficiency.PARTIAL
    assert assessment.fidelity_hint


def test_detect_numeric_conflicts_across_docs() -> None:
    evidence = [
        _ev("Lead (Pb): 0.4 ppm in assay table", name="doc-a.pdf"),
        _ev("Lead (Pb): 1.2 ppm in assay table", name="doc-b.pdf"),
    ]
    conflicts = detect_numeric_conflicts(evidence)
    assert conflicts
    assessment = assess_evidence(question="Give heavy metal content", evidence=evidence)
    assert CONFLICTING_EVIDENCE in assessment.warnings


def test_filter_graph_paths_drops_fake_mentions() -> None:
    chunk_id = uuid4()
    paths = [
        GraphPath(
            nodes=["TopicA", "TopicB"],
            relationships=["MENTIONS"],
            supporting_citations=[str(chunk_id), str(uuid4())],
        )
    ]
    kept, warnings = filter_grounded_graph_paths(
        paths, evidence_chunk_ids={chunk_id}
    )
    assert kept
    assert kept[0].relationships == []
    assert kept[0].supporting_citations == [str(chunk_id)]
    assert warnings


def test_build_messages_includes_sufficiency_and_conflict() -> None:
    tenant = TenantContext(tenant_id=new_id())
    evidence = [
        _ev("Cadmium (Cd): 0.4 ppm", name="a.pdf"),
        _ev("Cadmium (Cd): 2.0 ppm", name="b.pdf"),
    ]
    registry = CitationRegistry(tenant, evidence)
    messages = build_answer_messages(
        question="What is the cadmium content?",
        mode=RetrievalMode.HYBRID,
        registry=registry,
        evidence=evidence,
    )
    user = messages[1].content
    assert "Evidence sufficiency:" in user
    assert "CONFLICTING EVIDENCE" in user
