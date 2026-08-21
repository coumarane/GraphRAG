"""Offline evaluation metrics for retrieval and grounded answers."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field


class EvaluationCase(BaseModel):
    """Single question with expected retrieval/answer annotations."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    question: str
    modality: str = "text"
    expected_document_ids: list[str] = Field(default_factory=list)
    expected_chunk_ids: list[str] = Field(default_factory=list)
    expected_citation_ids: list[str] = Field(default_factory=list)
    expected_entities: list[str] = Field(default_factory=list)
    expected_graph_nodes: list[str] = Field(default_factory=list)
    gold_answer_contains: list[str] = Field(default_factory=list)
    unsupported_terms: list[str] = Field(default_factory=list)
    notes: str | None = None


class CaseScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    retrieval_hit: bool = False
    context_precision: float = 0.0
    context_recall: float = 0.0
    citation_precision: float = 0.0
    groundedness: float = 0.0
    unsupported_claim_rate: float = 0.0
    graph_path_hit: bool = False
    entity_hit: bool = False
    latency_ms: float = 0.0


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[CaseScore] = Field(default_factory=list)
    retrieval_hit_rate: float = 0.0
    mean_context_precision: float = 0.0
    mean_context_recall: float = 0.0
    mean_citation_precision: float = 0.0
    mean_groundedness: float = 0.0
    mean_unsupported_claim_rate: float = 0.0
    graph_path_accuracy: float = 0.0
    entity_resolution_precision: float = 0.0
    mean_latency_ms: float = 0.0


def precision_at_k(
    retrieved: Sequence[str],
    relevant: Sequence[str],
    *,
    k: int | None = None,
) -> float:
    if not retrieved:
        return 0.0
    selected = list(retrieved[:k] if k is not None else retrieved)
    if not selected:
        return 0.0
    relevant_set = set(relevant)
    hits = sum(1 for item in selected if item in relevant_set)
    return hits / len(selected)


def recall_at_k(
    retrieved: Sequence[str],
    relevant: Sequence[str],
    *,
    k: int | None = None,
) -> float:
    if not relevant:
        return 1.0
    selected = set(retrieved[:k] if k is not None else retrieved)
    hits = sum(1 for item in relevant if item in selected)
    return hits / len(relevant)


def citation_precision(claimed: Sequence[str], allowed: Sequence[str]) -> float:
    if not claimed:
        return 1.0
    allowed_set = set(allowed)
    hits = sum(1 for item in claimed if item in allowed_set)
    return hits / len(claimed)


def groundedness_score(answer: str, gold_contains: Sequence[str]) -> float:
    if not gold_contains:
        return 1.0 if answer.strip() else 0.0
    lowered = answer.lower()
    hits = sum(1 for term in gold_contains if term.lower() in lowered)
    return hits / len(gold_contains)


def unsupported_claim_rate(answer: str, unsupported_terms: Sequence[str]) -> float:
    if not unsupported_terms:
        return 0.0
    lowered = answer.lower()
    hits = sum(1 for term in unsupported_terms if term.lower() in lowered)
    return hits / len(unsupported_terms)


def aggregate_scores(scores: Sequence[CaseScore]) -> EvaluationReport:
    if not scores:
        return EvaluationReport()
    n = len(scores)
    return EvaluationReport(
        cases=list(scores),
        retrieval_hit_rate=sum(1 for s in scores if s.retrieval_hit) / n,
        mean_context_precision=sum(s.context_precision for s in scores) / n,
        mean_context_recall=sum(s.context_recall for s in scores) / n,
        mean_citation_precision=sum(s.citation_precision for s in scores) / n,
        mean_groundedness=sum(s.groundedness for s in scores) / n,
        mean_unsupported_claim_rate=sum(s.unsupported_claim_rate for s in scores) / n,
        graph_path_accuracy=sum(1 for s in scores if s.graph_path_hit) / n,
        entity_resolution_precision=sum(1 for s in scores if s.entity_hit) / n,
        mean_latency_ms=sum(s.latency_ms for s in scores) / n,
    )


__all__ = [
    "CaseScore",
    "EvaluationCase",
    "EvaluationReport",
    "aggregate_scores",
    "citation_precision",
    "groundedness_score",
    "precision_at_k",
    "recall_at_k",
    "unsupported_claim_rate",
]
