"""Evaluation corpus and metric harness tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from enterprise_rag.application.evaluation import (
    CORPUS_FILES,
    EvaluateRetrievalService,
    EvaluationPrediction,
    default_corpus_dir,
    list_corpus_files,
    load_evaluation_cases,
    precision_at_k,
    recall_at_k,
)


@pytest.mark.evaluation
def test_corpus_files_exist() -> None:
    files = list_corpus_files()
    assert len(files) == len(CORPUS_FILES)
    for path in files:
        assert path.is_file(), path
        assert path.stat().st_size > 100
    sample = Path("examples/sample.pdf")
    assert sample.is_file()


@pytest.mark.evaluation
def test_questions_load() -> None:
    cases = load_evaluation_cases()
    assert len(cases) >= 6
    assert {case.case_id for case in cases} >= {
        "viscosity-chart",
        "equation-4",
        "density-conflict",
    }


@pytest.mark.evaluation
def test_metric_helpers() -> None:
    assert precision_at_k(["a", "b", "c"], ["b"], k=2) == 0.5
    assert recall_at_k(["a", "b"], ["a", "b", "c"]) == pytest.approx(2 / 3)


@pytest.mark.evaluation
def test_offline_evaluation_harness() -> None:
    cases = load_evaluation_cases()
    service = EvaluateRetrievalService()

    def predictor(case):
        return EvaluationPrediction(
            retrieved_document_ids=list(case.expected_document_ids),
            retrieved_chunk_ids=list(case.expected_chunk_ids or case.expected_document_ids),
            citation_ids=list(case.expected_citation_ids or ["C1"]),
            entities=list(case.expected_entities),
            graph_nodes=list(case.expected_graph_nodes),
            answer=" ".join(case.gold_answer_contains),
        )

    report = service.run(cases, predictor)
    assert report.retrieval_hit_rate == 1.0
    assert report.mean_groundedness == 1.0
    assert report.mean_unsupported_claim_rate == 0.0
    assert default_corpus_dir().name == "corpus"
