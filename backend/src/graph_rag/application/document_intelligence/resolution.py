"""Resolve a per-upload ``DocumentIntelligenceIngestOptions`` into a concrete field list.

Pure and synchronous -- mirrors why ``catalog.py`` is its own module rather
than living in ``models.py``. Only resolves built-in models by key, plus
inline ``custom_fields``; resolving a *persisted* custom model by UUID during
ingestion is deferred to a later phase (nothing end-to-end exercises custom
models yet).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.application.document_intelligence.catalog import builtin_model_by_key
from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceIngestOptions,
    ModelFieldSpec,
)


class ResolvedExtractionRequest(BaseModel):
    """Concrete field list to extract, plus any non-fatal resolution warnings."""

    model_config = ConfigDict(extra="forbid")

    model_key: str | None = None
    model_name: str | None = None
    fields: list[ModelFieldSpec] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def resolve_requested_fields(
    options: DocumentIntelligenceIngestOptions,
) -> ResolvedExtractionRequest:
    """Merge a built-in model, ad-hoc custom fields, and a selection filter.

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
            warnings.append(
                f"model_id={options.model_id!r} did not match a built-in model; "
                "persisted custom models are not resolved during ingestion yet"
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
