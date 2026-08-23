"""``resolve_requested_fields`` tests (Phase 4)."""

from __future__ import annotations

from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceIngestOptions,
    FieldType,
    ModelFieldSpec,
)
from graph_rag.application.document_intelligence.resolution import resolve_requested_fields


def test_resolves_builtin_model_by_key() -> None:
    resolution = resolve_requested_fields(DocumentIntelligenceIngestOptions(model_id="sds"))
    assert resolution.model_key == "sds"
    assert resolution.model_name == "Safety Data Sheet"
    assert not resolution.warnings
    names = {field.name for field in resolution.fields}
    assert "product_name" in names
    assert "manufacturer" in names


def test_selected_fields_filters_to_subset() -> None:
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(model_id="sds", selected_fields=["product_name"])
    )
    assert [field.name for field in resolution.fields] == ["product_name"]
    assert not resolution.warnings


def test_unknown_model_id_warns_and_returns_no_fields() -> None:
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(model_id="does-not-exist")
    )
    assert resolution.fields == []
    assert resolution.warnings
    assert "does-not-exist" in resolution.warnings[0]


def test_custom_fields_only_ad_hoc_with_no_model() -> None:
    custom_field = ModelFieldSpec(name="batch_id", label="Batch ID", field_type=FieldType.STRING)
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(custom_fields=[custom_field])
    )
    assert resolution.model_key is None
    assert [field.name for field in resolution.fields] == ["batch_id"]


def test_custom_fields_override_same_named_builtin_field() -> None:
    custom_field = ModelFieldSpec(
        name="product_name", label="Custom Product Name", field_type=FieldType.STRING
    )
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(model_id="sds", custom_fields=[custom_field])
    )
    resolved = next(field for field in resolution.fields if field.name == "product_name")
    assert resolved.label == "Custom Product Name"


def test_unknown_selected_field_name_warns_and_is_dropped() -> None:
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(
            model_id="sds", selected_fields=["product_name", "not_a_real_field"]
        )
    )
    assert [field.name for field in resolution.fields] == ["product_name"]
    assert any("not_a_real_field" in warning for warning in resolution.warnings)


def test_no_model_and_no_custom_fields_resolves_to_empty() -> None:
    resolution = resolve_requested_fields(DocumentIntelligenceIngestOptions(enabled=True))
    assert resolution.fields == []
    assert not resolution.warnings
