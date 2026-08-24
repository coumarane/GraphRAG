"""``resolve_requested_fields`` tests (Phases 4, 7)."""

from __future__ import annotations

from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceIngestOptions,
    FieldType,
    ModelFieldSpec,
)
from graph_rag.application.document_intelligence.resolution import resolve_requested_fields
from graph_rag.domain.document_intelligence.records import (
    DocumentIntelligenceModelFieldRecord,
    DocumentIntelligenceModelRecord,
)
from graph_rag.domain.ids import new_id


def _custom_model_record(*, model_key: str = "invoice") -> DocumentIntelligenceModelRecord:
    tenant_id = new_id()
    model_id = new_id()
    return DocumentIntelligenceModelRecord(
        model_id=model_id,
        tenant_id=tenant_id,
        model_key=model_key,
        name="Invoice",
        fields=[
            DocumentIntelligenceModelFieldRecord(
                field_id=new_id(),
                model_id=model_id,
                tenant_id=tenant_id,
                name="invoice_number",
                label="Invoice number",
                field_type="string",
                default_selected=True,
                sort_order=0,
            ),
            DocumentIntelligenceModelFieldRecord(
                field_id=new_id(),
                model_id=model_id,
                tenant_id=tenant_id,
                name="total_amount",
                label="Total amount",
                field_type="currency",
                sort_order=1,
            ),
        ],
    )


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


def test_resolves_persisted_custom_model_by_model_key() -> None:
    record = _custom_model_record()
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(model_id="invoice"), custom_models=[record]
    )
    assert resolution.model_key == "invoice"
    assert resolution.model_name == "Invoice"
    assert not resolution.warnings
    names = {field.name for field in resolution.fields}
    assert names == {"invoice_number", "total_amount"}


def test_resolves_persisted_custom_model_by_model_id_uuid_string() -> None:
    record = _custom_model_record(model_key="invoice-v2")
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(model_id=str(record.model_id)),
        custom_models=[record],
    )
    assert resolution.model_key == "invoice-v2"
    assert {field.name for field in resolution.fields} == {"invoice_number", "total_amount"}


def test_custom_model_not_in_supplied_list_falls_back_to_no_fields_warning() -> None:
    """Cross-tenant isolation is enforced by the caller only ever passing its own
    tenant's list_models() result -- a model_id belonging to another tenant simply
    never appears here and must fall back exactly like an unknown id."""
    other_tenants_record = _custom_model_record(model_key="invoice")
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(model_id="not-this-tenants-model"),
        custom_models=[other_tenants_record],
    )
    assert resolution.fields == []
    assert resolution.warnings
    assert "not-this-tenants-model" in resolution.warnings[0]


def test_builtin_model_id_takes_precedence_over_same_named_custom_model() -> None:
    record = _custom_model_record(model_key="sds")  # shadows the builtin key on purpose
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(model_id="sds"), custom_models=[record]
    )
    assert resolution.model_name == "Safety Data Sheet"  # builtin wins, not the custom record


def test_custom_model_fields_combine_with_selected_fields_filter() -> None:
    record = _custom_model_record()
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(model_id="invoice", selected_fields=["invoice_number"]),
        custom_models=[record],
    )
    assert [field.name for field in resolution.fields] == ["invoice_number"]


def test_custom_model_promote_to_document_metadata_flag_survives_resolution() -> None:
    tenant_id = new_id()
    model_id = new_id()
    record = DocumentIntelligenceModelRecord(
        model_id=model_id,
        tenant_id=tenant_id,
        model_key="invoice",
        name="Invoice",
        fields=[
            DocumentIntelligenceModelFieldRecord(
                field_id=new_id(),
                model_id=model_id,
                tenant_id=tenant_id,
                name="vendor_name",
                label="Vendor name",
                field_type="string",
                promote_to_document_metadata=True,
            ),
            DocumentIntelligenceModelFieldRecord(
                field_id=new_id(),
                model_id=model_id,
                tenant_id=tenant_id,
                name="notes",
                label="Notes",
                field_type="string",
            ),
        ],
    )
    resolution = resolve_requested_fields(
        DocumentIntelligenceIngestOptions(model_id="invoice"), custom_models=[record]
    )
    by_name = {field.name: field for field in resolution.fields}
    assert by_name["vendor_name"].promote_to_document_metadata is True
    assert by_name["notes"].promote_to_document_metadata is False
