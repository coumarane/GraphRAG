"""Resolve a per-upload ``DocumentIntelligenceIngestOptions`` into a concrete field list.

Pure and synchronous -- mirrors why ``catalog.py`` is its own module rather
than living in ``models.py``. Resolves built-in models by key, a persisted
custom model (via the ``custom_models`` parameter, pre-fetched by the caller
-- see ``_find_custom_model``), and inline ``custom_fields``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.application.document_intelligence.catalog import builtin_model_by_key
from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceIngestOptions,
    ModelFieldSpec,
)
from graph_rag.domain.document_intelligence.records import DocumentIntelligenceModelRecord


class ResolvedExtractionRequest(BaseModel):
    """Concrete field list to extract, plus any non-fatal resolution warnings."""

    model_config = ConfigDict(extra="forbid")

    model_key: str | None = None
    model_name: str | None = None
    fields: list[ModelFieldSpec] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _matches_model_id(record: DocumentIntelligenceModelRecord, model_id: str) -> bool:
    """A record matches either by its stable ``model_key`` slug or by UUID string."""
    if record.model_key == model_id.strip().lower():
        return True
    try:
        return record.model_id == UUID(model_id.strip())
    except ValueError:
        return False


def _find_custom_model(
    model_id: str, custom_models: list[DocumentIntelligenceModelRecord]
) -> DocumentIntelligenceModelRecord | None:
    for record in custom_models:
        if _matches_model_id(record, model_id):
            return record
    return None


def resolve_requested_fields(
    options: DocumentIntelligenceIngestOptions,
    *,
    custom_models: list[DocumentIntelligenceModelRecord] | None = None,
) -> ResolvedExtractionRequest:
    """Merge a built-in model, a persisted custom model, ad-hoc custom fields, and a selection
    filter.

    ``custom_models`` is the *already tenant-scoped* set of the caller's
    persisted custom models (the caller fetches this via
    ``DocumentIntelligenceModelRepository.list_models(tenant)`` before calling
    in) -- this function does no repo access and knows nothing about tenancy
    itself, mirroring how ``reuse.py``'s ``select_reuse_candidate``/
    ``split_reused_and_delta_fields`` take pre-fetched repo results as plain
    arguments.

    An empty ``fields`` result (unresolvable ``model_id`` and no usable
    ``custom_fields``) is a valid, expected outcome -- the caller decides how
    to handle it (this function never raises).
    """
    warnings: list[str] = []
    model_key: str | None = None
    model_name: str | None = None
    merged: dict[str, ModelFieldSpec] = {}

    if options.model_id:
        builtin = builtin_model_by_key(options.model_id)
        if builtin is not None:
            model_key = builtin.model_key
            model_name = builtin.name
            for field in builtin.fields:
                merged[field.name] = field
        else:
            custom = _find_custom_model(options.model_id, custom_models or [])
            if custom is not None:
                model_key = custom.model_key
                model_name = custom.name
                for custom_field in custom.fields:
                    merged[custom_field.name] = ModelFieldSpec(
                        name=custom_field.name,
                        label=custom_field.label,
                        field_type=custom_field.field_type,  # type: ignore[arg-type]
                        default_selected=custom_field.default_selected,
                    )
            else:
                warnings.append(
                    f"model_id={options.model_id!r} did not match a built-in or "
                    "persisted custom model"
                )

    for field in options.custom_fields or ():
        merged[field.name] = field

    fields = list(merged.values())

    if options.selected_fields is not None:
        selected = set(options.selected_fields)
        unknown = selected - merged.keys()
        for name in sorted(unknown):
            warnings.append(f"selected_fields contains unknown field {name!r}; ignored")
        fields = [field for field in fields if field.name in selected]

    return ResolvedExtractionRequest(
        model_key=model_key,
        model_name=model_name,
        fields=fields,
        warnings=warnings,
    )
