"""Application-level grounded-generation policy (not prompt-only).

Enforces evidence sufficiency, conflict detection, graph-path hygiene, and
pre-return grounding checks used by QueryDocumentsService / GenerateAnswerService.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from enterprise_rag.domain.generation.claim_fidelity import (
    CLAIM_STRENGTH_OVERREACH,
    detect_claim_strength_overreach,
    question_asks_normative_value,
    soften_normative_overreach,
)
from enterprise_rag.domain.retrieval.models import GraphPath, RetrievedEvidence

_NUMERIC_FACT_RE = re.compile(
    r"(?i)(?P<label>[A-Za-z][A-Za-z0-9\-]{1,24})"
    r"(?:\s*\([^)]{0,24}\))?"
    r"\s*[:\-]\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|ppm|μm|um|mg/kg|°C|celsius)\b"
)

SUFFICIENCY_INSUFFICIENT = "evidence_insufficient"
SUFFICIENCY_PARTIAL = "evidence_partial"
CONFLICTING_EVIDENCE = "conflicting_evidence"
GRAPH_PATH_FILTERED = "graph_path_filtered"
CROSS_DOC_UNAUTHORIZED = "cross_document_search_unauthorized"


class EvidenceSufficiency(StrEnum):
    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class EvidenceConflict:
    """Two evidence items that disagree on a comparable numeric fact."""

    label: str
    unit: str
    values: tuple[str, ...]
    document_names: tuple[str, ...]


@dataclass
class GroundingAssessment:
    """Deterministic pre/post generation grounding assessment."""

    sufficiency: EvidenceSufficiency
    conflicts: list[EvidenceConflict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fidelity_hint: str | None = None


def assess_evidence(
    *,
    question: str,
    evidence: Sequence[RetrievedEvidence],
    min_top_score: float = 0.12,
) -> GroundingAssessment:
    """Evaluate whether retrieved evidence is enough to answer grounded."""
    warnings: list[str] = []
    if not evidence:
        return GroundingAssessment(
            sufficiency=EvidenceSufficiency.INSUFFICIENT,
            warnings=[SUFFICIENCY_INSUFFICIENT],
        )

    scores = [float(item.score or 0.0) for item in evidence]
    top = max(scores) if scores else 0.0
    conflicts = detect_numeric_conflicts(evidence)
    if conflicts:
        warnings.append(CONFLICTING_EVIDENCE)

    texts = [item.text for item in evidence if item.text]
    from enterprise_rag.domain.generation.claim_fidelity import (
        build_claim_fidelity_hint,
        evidence_states_normative_value,
    )

    fidelity = build_claim_fidelity_hint(question, texts)
    if question_asks_normative_value(question) and not evidence_states_normative_value(texts):
        # Normative ask with only demo/test evidence → partial (answer supported part).
        return GroundingAssessment(
            sufficiency=EvidenceSufficiency.PARTIAL,
            conflicts=conflicts,
            warnings=[*warnings, SUFFICIENCY_PARTIAL],
            fidelity_hint=fidelity,
        )

    if top < min_top_score:
        return GroundingAssessment(
            sufficiency=EvidenceSufficiency.INSUFFICIENT,
            conflicts=conflicts,
            warnings=[*warnings, SUFFICIENCY_INSUFFICIENT, "low_retrieval_score"],
            fidelity_hint=fidelity,
        )

    return GroundingAssessment(
        sufficiency=EvidenceSufficiency.SUFFICIENT,
        conflicts=conflicts,
        warnings=warnings,
        fidelity_hint=fidelity,
    )


def detect_numeric_conflicts(
    evidence: Sequence[RetrievedEvidence],
) -> list[EvidenceConflict]:
    """Find label+unit pairs with divergent values across different documents."""
    by_key: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for item in evidence:
        doc = (item.document_name or str(item.document_id)).strip()
        text = item.text or ""
        for match in _NUMERIC_FACT_RE.finditer(text):
            label = match.group("label").strip().casefold()
            unit = (match.group("unit") or "").casefold()
            value = match.group("value")
            if len(label) < 2 or not unit:
                continue
            by_key[(label, unit)][value].add(doc)

    conflicts: list[EvidenceConflict] = []
    for (label, unit), value_map in by_key.items():
        if len(value_map) < 2:
            continue
        # Require at least two documents when values differ.
        docs = {doc for docs in value_map.values() for doc in docs}
        if len(docs) < 2:
            continue
        values = tuple(sorted(value_map.keys(), key=lambda item: float(item)))
        doc_names = tuple(sorted(docs))
        conflicts.append(
            EvidenceConflict(
                label=label,
                unit=unit,
                values=values,
                document_names=doc_names,
            )
        )
    return conflicts[:8]


def format_conflict_hint(conflicts: Sequence[EvidenceConflict]) -> str | None:
    if not conflicts:
        return None
    lines = [
        "CONFLICTING EVIDENCE (required):",
        "- Retrieved sources disagree on comparable numeric facts.",
        "- Do NOT silently pick one value. Present each value with its citation.",
    ]
    for conflict in conflicts[:4]:
        vals = ", ".join(f"{value}{conflict.unit}" for value in conflict.values)
        docs = "; ".join(conflict.document_names[:4])
        lines.append(f"- {conflict.label}: {vals} (sources: {docs})")
    return "\n".join(lines)


def filter_grounded_graph_paths(
    paths: Sequence[GraphPath],
    *,
    evidence_chunk_ids: set[UUID],
) -> tuple[list[GraphPath], list[str]]:
    """Keep only paths whose supporting citations refer to retrieved chunks.

    Drops placeholder relationship bags like a lone MENTIONS with no neighbors.
    """
    warnings: list[str] = []
    kept: list[GraphPath] = []
    for path in paths:
        cites: list[str] = []
        for raw in path.supporting_citations:
            try:
                cid = UUID(str(raw))
            except Exception:  # noqa: BLE001
                continue
            if cid in evidence_chunk_ids:
                cites.append(str(cid))
        rels = [rel for rel in path.relationships if rel and rel.upper() != "MENTIONS"]
        if not path.nodes:
            continue
        if path.relationships and not rels and path.relationships == ["MENTIONS"]:
            # Topic bag without real edges — keep nodes, clear fake relationship.
            warnings.append(GRAPH_PATH_FILTERED)
            kept.append(
                path.model_copy(
                    update={
                        "relationships": [],
                        "supporting_citations": cites,
                        "metadata": {
                            **dict(path.metadata),
                            "filtered_placeholder_mentions": True,
                        },
                    }
                )
            )
            continue
        kept.append(
            path.model_copy(
                update={
                    "relationships": rels or list(path.relationships),
                    "supporting_citations": cites,
                }
            )
        )
    if len(kept) < len(paths):
        warnings.append(GRAPH_PATH_FILTERED)
    return kept, list(dict.fromkeys(warnings))


def finalize_grounded_answer(
    *,
    question: str,
    answer: str,
    evidence: Sequence[RetrievedEvidence],
    warnings: Sequence[str],
    cross_document_authorized: bool,
    pinned_document_ids: Sequence[UUID],
) -> tuple[str, list[str]]:
    """Pre-return policy checks; may soften answer and append warnings."""
    out_warnings = list(warnings)
    texts = [item.text for item in evidence if item.text]
    final_answer = answer

    if detect_claim_strength_overreach(question, final_answer, texts):
        if CLAIM_STRENGTH_OVERREACH not in out_warnings:
            out_warnings.append(CLAIM_STRENGTH_OVERREACH)
        final_answer = soften_normative_overreach(final_answer)

    # Cross-doc answer while still pinned without authorization is a policy breach.
    if pinned_document_ids and not cross_document_authorized:
        cited_docs = {
            item.document_id
            for item in evidence
            if item.document_id not in set(pinned_document_ids)
        }
        # Evidence list is already scoped by retrieval; this guards generation misuse.
        if cited_docs:
            out_warnings.append(CROSS_DOC_UNAUTHORIZED)

    return final_answer, list(dict.fromkeys(out_warnings))
