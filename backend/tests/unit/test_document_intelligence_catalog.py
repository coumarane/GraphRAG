"""Built-in Document Intelligence model catalog tests (Phase 2)."""

from __future__ import annotations

from graph_rag.application.document_intelligence.catalog import (
    BUILTIN_DOCUMENT_INTELLIGENCE_MODELS,
    builtin_model_by_key,
)
from graph_rag.application.document_intelligence.models import ModelType


def test_builtin_models_are_prebuilt_with_at_least_one_field() -> None:
    assert len(BUILTIN_DOCUMENT_INTELLIGENCE_MODELS) >= 7
    for model in BUILTIN_DOCUMENT_INTELLIGENCE_MODELS:
        assert model.model_type == ModelType.PREBUILT
        assert model.is_builtin is True
        assert model.model_id is None
        assert len(model.fields) >= 1


def test_builtin_model_keys_are_unique() -> None:
    keys = [model.model_key for model in BUILTIN_DOCUMENT_INTELLIGENCE_MODELS]
    assert len(keys) == len(set(keys))


def test_builtin_model_by_key_is_case_insensitive() -> None:
    found = builtin_model_by_key("SDS")
    assert found is not None
    assert found.model_key == "sds"


def test_builtin_model_by_key_returns_none_for_unknown_key() -> None:
    assert builtin_model_by_key("does-not-exist") is None


def test_at_least_one_field_default_selected_per_model() -> None:
    """A checklist UI defaulting to nothing selected would be a poor default."""
    for model in BUILTIN_DOCUMENT_INTELLIGENCE_MODELS:
        assert any(field.default_selected for field in model.fields), model.model_key
