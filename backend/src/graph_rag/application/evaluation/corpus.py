"""Load evaluation corpus metadata and question cases."""

from __future__ import annotations

import json
from pathlib import Path

from graph_rag.application.evaluation.metrics import EvaluationCase

CORPUS_FILES = (
    "text_heavy.pdf",
    "scanned.pdf",
    "scientific_equations.pdf",
    "charts.pdf",
    "complex_tables.pdf",
    "shared_entities_a.pdf",
    "shared_entities_b.pdf",
)


def default_corpus_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "evaluation" / "corpus"


def default_questions_path() -> Path:
    return Path(__file__).resolve().parents[4] / "evaluation" / "questions.json"


def list_corpus_files(corpus_dir: Path | None = None) -> list[Path]:
    root = corpus_dir or default_corpus_dir()
    return [root / name for name in CORPUS_FILES]


def load_evaluation_cases(path: Path | None = None) -> list[EvaluationCase]:
    questions_path = path or default_questions_path()
    raw = json.loads(questions_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        msg = "evaluation questions must be a JSON array"
        raise ValueError(msg)
    return [EvaluationCase.model_validate(item) for item in raw]


__all__ = [
    "CORPUS_FILES",
    "default_corpus_dir",
    "default_questions_path",
    "list_corpus_files",
    "load_evaluation_cases",
]
