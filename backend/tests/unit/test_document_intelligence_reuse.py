"""Pure cost-control reuse function tests (Phase 6)."""

from __future__ import annotations

from graph_rag.application.document_intelligence.models import FieldType, ModelFieldSpec
from graph_rag.application.document_intelligence.reuse import (
    clone_field_for_new_run,
    compute_fingerprint,
    select_reuse_candidate,
    split_reused_and_delta_fields,
)
from graph_rag.domain.document_intelligence.records import (
    DocumentExtractedFieldRecord,
    DocumentExtractionRunRecord,
)
from graph_rag.domain.ids import new_id

_TENANT_ID = new_id()
_DOCUMENT_ID = new_id()
_VERSION_ID = new_id()


def _fields(*names_and_types: tuple[str, FieldType]) -> list[ModelFieldSpec]:
    return [
        ModelFieldSpec(name=name, label=name.title(), field_type=field_type)
        for name, field_type in names_and_types
    ]


def _run(
    *,
    status: str = "completed",
    model_key: str | None = "sds",
    provider: str = "internal",
    plugin_version: str = "0.5.0",
    fingerprint: str | None = None,
    selected_fields: list[str] | None = None,
) -> DocumentExtractionRunRecord:
    return DocumentExtractionRunRecord(
        run_id=new_id(),
        tenant_id=_TENANT_ID,
        document_id=_DOCUMENT_ID,
        version_id=_VERSION_ID,
        model_key=model_key,
        provider=provider,
        plugin_version=plugin_version,
        status=status,
        fingerprint=fingerprint,
        selected_fields=selected_fields or [],
    )


def _field_row(name: str, run_id) -> DocumentExtractedFieldRecord:
    return DocumentExtractedFieldRecord(
        extracted_field_id=new_id(),
        tenant_id=_TENANT_ID,
        run_id=run_id,
        name=name,
        value="v",
        extraction_method="RULES",
    )


def test_compute_fingerprint_is_stable_regardless_of_field_order() -> None:
    fields_a = _fields(("product_name", FieldType.STRING), ("lot_number", FieldType.STRING))
    fields_b = list(reversed(fields_a))
    fp_a = compute_fingerprint(
        content_hash="abc123", plugin_version="0.5.0", model_key="sds", fields=fields_a
    )
    fp_b = compute_fingerprint(
        content_hash="abc123", plugin_version="0.5.0", model_key="sds", fields=fields_b
    )
    assert fp_a == fp_b


def test_compute_fingerprint_changes_with_content_hash() -> None:
    fields = _fields(("product_name", FieldType.STRING))
    fp_a = compute_fingerprint(
        content_hash="abc123", plugin_version="0.5.0", model_key="sds", fields=fields
    )
    fp_b = compute_fingerprint(
        content_hash="def456", plugin_version="0.5.0", model_key="sds", fields=fields
    )
    assert fp_a != fp_b


def test_compute_fingerprint_changes_with_plugin_version() -> None:
    fields = _fields(("product_name", FieldType.STRING))
    fp_a = compute_fingerprint(
        content_hash="abc123", plugin_version="0.5.0", model_key="sds", fields=fields
    )
    fp_b = compute_fingerprint(
        content_hash="abc123", plugin_version="0.6.0", model_key="sds", fields=fields
    )
    assert fp_a != fp_b


def test_compute_fingerprint_changes_with_model_key() -> None:
    fields = _fields(("product_name", FieldType.STRING))
    fp_a = compute_fingerprint(
        content_hash="abc123", plugin_version="0.5.0", model_key="sds", fields=fields
    )
    fp_b = compute_fingerprint(
        content_hash="abc123", plugin_version="0.5.0", model_key="layout", fields=fields
    )
    assert fp_a != fp_b


def test_compute_fingerprint_changes_with_field_set() -> None:
    fp_a = compute_fingerprint(
        content_hash="abc123",
        plugin_version="0.5.0",
        model_key="sds",
        fields=_fields(("product_name", FieldType.STRING)),
    )
    fp_b = compute_fingerprint(
        content_hash="abc123",
        plugin_version="0.5.0",
        model_key="sds",
        fields=_fields(("product_name", FieldType.STRING), ("lot_number", FieldType.STRING)),
    )
    assert fp_a != fp_b


def test_compute_fingerprint_changes_with_field_type_only() -> None:
    fp_a = compute_fingerprint(
        content_hash="abc123",
        plugin_version="0.5.0",
        model_key="sds",
        fields=_fields(("quantity", FieldType.STRING)),
    )
    fp_b = compute_fingerprint(
        content_hash="abc123",
        plugin_version="0.5.0",
        model_key="sds",
        fields=_fields(("quantity", FieldType.NUMBER)),
    )
    assert fp_a != fp_b


def test_select_reuse_candidate_matches_model_provider_plugin_version() -> None:
    matching = _run(selected_fields=["a"], fingerprint="fp1")
    runs = [matching]
    candidate = select_reuse_candidate(
        runs, model_key="sds", provider="internal", plugin_version="0.5.0"
    )
    assert candidate is matching
    # selected_fields/fingerprint are irrelevant to candidate selection.
    other = select_reuse_candidate(
        [_run(selected_fields=["totally", "different"], fingerprint="other-fp")],
        model_key="sds",
        provider="internal",
        plugin_version="0.5.0",
    )
    assert other is not None


def test_select_reuse_candidate_excludes_failed_status() -> None:
    runs = [_run(status="failed")]
    assert (
        select_reuse_candidate(runs, model_key="sds", provider="internal", plugin_version="0.5.0")
        is None
    )


def test_select_reuse_candidate_excludes_plugin_version_mismatch() -> None:
    """A provider version bump invalidates reuse of older runs."""
    runs = [_run(plugin_version="0.4.0")]
    assert (
        select_reuse_candidate(runs, model_key="sds", provider="internal", plugin_version="0.5.0")
        is None
    )


def test_select_reuse_candidate_excludes_model_key_mismatch() -> None:
    runs = [_run(model_key="layout")]
    assert (
        select_reuse_candidate(runs, model_key="sds", provider="internal", plugin_version="0.5.0")
        is None
    )


def test_select_reuse_candidate_empty_input_returns_none() -> None:
    assert (
        select_reuse_candidate([], model_key="sds", provider="internal", plugin_version="0.5.0")
        is None
    )


def test_select_reuse_candidate_picks_first_newest_match() -> None:
    newest = _run()
    older = _run()
    candidate = select_reuse_candidate(
        [newest, older], model_key="sds", provider="internal", plugin_version="0.5.0"
    )
    assert candidate is newest


def test_split_full_overlap_yields_empty_delta() -> None:
    run_id = new_id()
    candidate_fields = [_field_row("product_name", run_id), _field_row("lot_number", run_id)]
    requested = _fields(("product_name", FieldType.STRING), ("lot_number", FieldType.STRING))
    reused, delta = split_reused_and_delta_fields(requested, candidate_fields)
    assert {row.name for row in reused} == {"product_name", "lot_number"}
    assert delta == []


def test_split_no_overlap_yields_all_delta() -> None:
    requested = _fields(("product_name", FieldType.STRING))
    reused, delta = split_reused_and_delta_fields(requested, [])
    assert reused == []
    assert [field.name for field in delta] == ["product_name"]


def test_split_never_reuses_a_requested_but_unresolved_field() -> None:
    """A name in a prior run's selected_fields with no row must still land in delta.

    split_reused_and_delta_fields never even accepts selected_fields as
    input -- this proves a requested-but-never-resolved field is always
    retried, never permanently silently missed.
    """
    run_id = new_id()
    candidate_fields = [_field_row("product_name", run_id)]
    requested = _fields(("product_name", FieldType.STRING), ("lot_number", FieldType.STRING))
    reused, delta = split_reused_and_delta_fields(requested, candidate_fields)
    assert [row.name for row in reused] == ["product_name"]
    assert [field.name for field in delta] == ["lot_number"]


def test_clone_field_for_new_run_resets_ids_and_timestamps() -> None:
    from datetime import UTC, datetime

    original_run_id = new_id()
    original = DocumentExtractedFieldRecord(
        extracted_field_id=new_id(),
        tenant_id=_TENANT_ID,
        run_id=original_run_id,
        name="product_name",
        value="Acme Widget",
        confidence=0.8,
        confidence_band="MEDIUM",
        extraction_method="RULES",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    new_field_id = new_id()
    new_run_id = new_id()
    cloned = clone_field_for_new_run(
        original, new_extracted_field_id=new_field_id, new_run_id=new_run_id
    )
    assert cloned.extracted_field_id == new_field_id
    assert cloned.run_id == new_run_id
    assert cloned.created_at is None
    assert cloned.updated_at is None
    assert cloned.name == original.name
    assert cloned.value == original.value
    assert cloned.confidence == original.confidence
    assert cloned.extraction_method == original.extraction_method
