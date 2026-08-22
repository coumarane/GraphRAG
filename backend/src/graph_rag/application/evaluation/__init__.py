"""Offline evaluation use cases."""

from graph_rag.application.evaluation.corpus import (
    CORPUS_FILES,
    default_corpus_dir,
    default_questions_path,
    list_corpus_files,
    load_evaluation_cases,
)
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
from graph_rag.application.evaluation.runner import (
    EvaluateRetrievalService,
    EvaluationPrediction,
)

__all__ = [
    "CORPUS_FILES",
    "CaseScore",
    "EvaluateRetrievalService",
    "EvaluationCase",
    "EvaluationPrediction",
    "EvaluationReport",
    "aggregate_scores",
    "citation_precision",
    "default_corpus_dir",
    "default_questions_path",
    "groundedness_score",
    "list_corpus_files",
    "load_evaluation_cases",
    "precision_at_k",
    "recall_at_k",
    "unsupported_claim_rate",
]
