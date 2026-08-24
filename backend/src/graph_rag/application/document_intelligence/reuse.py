"""Cost-control extraction reuse: fingerprint audit trail + delta-field selection.

One mechanism, not the two the original design sketch described (an exact-
fingerprint short-circuit plus a separate incremental diff). A literal
"identical fingerprint -> copy everything, never call the provider" rule has
a real footgun: if a prior run left one field permanently unresolved (no
row, but the run still completed with a warning), a fingerprint-only check
would keep matching forever and that field would never be retried, silently,
indefinitely. Splitting reused-vs-delta by *row presence* instead -- never by
fingerprint equality, never by a candidate run's ``selected_fields`` -- fixes
this for free and produces identical zero-cost behavior in the common case
(everything already has a row -> delta is empty -> provider never called).
``fingerprint`` is still computed and stored on every run, but purely for
audit/observability, never as a reuse-lookup key.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from graph_rag.application.document_intelligence.models import (
    DocumentExtractionRunStatus,
    ModelFieldSpec,
)
from graph_rag.domain.document_intelligence.records import (
    DocumentExtractedFieldRecord,
    DocumentExtractionRunRecord,
)

REUSABLE_RUN_STATUSES = frozenset(
    {
        DocumentExtractionRunStatus.COMPLETED.value,
        DocumentExtractionRunStatus.COMPLETED_WITH_WARNINGS.value,
    }
)


def compute_fingerprint(
    *,
    content_hash: str,
    plugin_version: str,
    model_key: str | None,
    fields: list[ModelFieldSpec],
) -> str:
    """Audit-only -- never used as a reuse-lookup key (see module docstring)."""
    parts = [content_hash, plugin_version, model_key or ""]
    parts.extend(sorted(f"{field.name}:{field.field_type.value}" for field in fields))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def select_reuse_candidate(
    prior_runs: list[DocumentExtractionRunRecord],
    *,
    model_key: str | None,
    provider: str,
    plugin_version: str,
) -> DocumentExtractionRunRecord | None:
    """First (newest) prior run matching (model_key, provider, plugin_version).

    ``prior_runs`` is expected newest-first, as
    ``DocumentExtractionRepository.list_runs_for_version`` returns. A
    candidate's ``selected_fields``/``fingerprint`` are deliberately ignored
    here -- only row presence (checked separately by
    ``split_reused_and_delta_fields``) decides what's actually reusable.
    """
    for run in prior_runs:
        if (
            run.status in REUSABLE_RUN_STATUSES
            and run.model_key == model_key
            and run.provider == provider
            and run.plugin_version == plugin_version
        ):
            return run
    return None


def split_reused_and_delta_fields(
    requested_fields: list[ModelFieldSpec],
    candidate_fields: list[DocumentExtractedFieldRecord],
) -> tuple[list[DocumentExtractedFieldRecord], list[ModelFieldSpec]]:
    """Split purely by row presence -- never reads a candidate run's selected_fields.

    A field that was previously requested but never resolved has no row, so
    it always lands in ``delta`` and gets retried -- never a permanent miss.
    """
    by_name = {row.name: row for row in candidate_fields}
    reused = [by_name[field.name] for field in requested_fields if field.name in by_name]
    delta = [field for field in requested_fields if field.name not in by_name]
    return reused, delta


def clone_field_for_new_run(
    field: DocumentExtractedFieldRecord,
    *,
    new_extracted_field_id: UUID,
    new_run_id: UUID,
) -> DocumentExtractedFieldRecord:
    """Reset id/run/timestamps; every other field carries over byte-identical.

    ``created_at``/``updated_at`` must reset to ``None``, not just the id
    fields -- the in-memory repository only stamps ``now()`` when both are
    ``None``, so a naive copy would silently carry the original run's
    timestamp into the clone (the SQLAlchemy backend is unaffected --
    ``server_default=func.now()`` ignores incoming timestamps).
    """
    return field.model_copy(
        update={
            "extracted_field_id": new_extracted_field_id,
            "run_id": new_run_id,
            "created_at": None,
            "updated_at": None,
        }
    )
