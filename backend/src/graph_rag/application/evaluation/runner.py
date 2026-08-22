"""Score retrieval/answer payloads against annotated evaluation cases."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from graph_rag.application.evaluation.metrics import (
    CaseScore,
    EvaluationCase,
    EvaluationReport,
    aggregate_scores,
    citation_precision,
    groundedness_score,
    precision_at_k,
    recall_at_k,
    unsupported_claim_rate,
)


@dataclass(frozen=True)
class EvaluationPrediction:
    """Model/system outputs for one evaluation case."""

    retrieved_document_ids: Sequence[str] = ()
    retrieved_chunk_ids: Sequence[str] = ()
    citation_ids: Sequence[str] = ()
    entities: Sequence[str] = ()
    graph_nodes: Sequence[str] = ()
    answer: str = ""


Predictor = Callable[[EvaluationCase], EvaluationPrediction]


class EvaluateRetrievalService:
    """Compute offline evaluation metrics from annotated cases + predictions."""

    def score_case(self, case: EvaluationCase, prediction: EvaluationPrediction) -> CaseScore:
        retrieved_docs = list(prediction.retrieved_document_ids)
        retrieved_chunks = list(prediction.retrieved_chunk_ids)
        relevant_docs = case.expected_document_ids
        relevant_chunks = case.expected_chunk_ids or case.expected_document_ids
        retrieved_for_context = retrieved_chunks or retrieved_docs
        hit = bool(set(retrieved_docs) & set(relevant_docs)) if relevant_docs else bool(
            retrieved_for_context
        )
        entity_hit = True
        if case.expected_entities:
            predicted = {item.lower() for item in prediction.entities}
            expected = {item.lower() for item in case.expected_entities}
            entity_hit = bool(predicted & expected)
        graph_hit = True
        if case.expected_graph_nodes:
            predicted_nodes = {item.lower() for item in prediction.graph_nodes}
            expected_nodes = {item.lower() for item in case.expected_graph_nodes}
            graph_hit = bool(predicted_nodes & expected_nodes)
        allowed_citations = case.expected_citation_ids or [
            f"C{index}" for index in range(1, len(retrieved_for_context) + 1)
        ]
        return CaseScore(
            case_id=case.case_id,
            retrieval_hit=hit,
            context_precision=precision_at_k(retrieved_for_context, relevant_chunks),
            context_recall=recall_at_k(retrieved_for_context, relevant_chunks),
            citation_precision=citation_precision(prediction.citation_ids, allowed_citations),
            groundedness=groundedness_score(prediction.answer, case.gold_answer_contains),
            unsupported_claim_rate=unsupported_claim_rate(
                prediction.answer,
                case.unsupported_terms,
            ),
            graph_path_hit=graph_hit,
            entity_hit=entity_hit,
        )

    def run(
        self,
        cases: Sequence[EvaluationCase],
        predictor: Predictor,
    ) -> EvaluationReport:
        scores: list[CaseScore] = []
        for case in cases:
            started = time.perf_counter()
            prediction = predictor(case)
            scored = self.score_case(case, prediction)
            scores.append(
                scored.model_copy(
                    update={"latency_ms": (time.perf_counter() - started) * 1000.0}
                )
            )
        return aggregate_scores(scores)


__all__ = ["EvaluateRetrievalService", "EvaluationPrediction", "Predictor"]
