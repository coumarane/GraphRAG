"""In-memory document/field search for local mode and tests.

Delegates storage entirely to the existing ``InMemoryDocumentRepository``/
``InMemoryDocumentExtractionRepository`` instances rather than duplicating
state -- this is a query layer over their existing dicts, not a third store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from graph_rag.domain.document_intelligence.records import DocumentExtractedFieldRecord
from graph_rag.domain.document_search.models import (
    DocumentSearchHit,
    DocumentSearchQuery,
    DocumentSearchResult,
    FieldFilter,
    FieldFilterOperator,
)
from graph_rag.domain.ingestion.records import DocumentRecord
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.document_intelligence import (
    InMemoryDocumentExtractionRepository,
)
from graph_rag.infrastructure.persistence.memory.lifecycle import InMemoryDocumentRepository


def _coerce_comparable(value: Any) -> Any:
    """Best-effort coercion for gt/gte/lt/lte/between comparisons.

    Extracted field values are JSON (str/int/float/bool/None); dates are
    stored as ISO strings. Try numeric, then ISO date/datetime, else leave
    as-is so string comparison is the fallback.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return value


def _matches_operator(
    field_value: Any,
    operator: FieldFilterOperator,
    target: Any,
    target_to: Any,
) -> bool:
    if operator is FieldFilterOperator.EQ:
        if isinstance(field_value, str) and isinstance(target, str):
            return field_value.casefold() == target.casefold()
        return bool(field_value == target)
    if operator is FieldFilterOperator.CONTAINS:
        return str(target).casefold() in str(field_value).casefold()
    left = _coerce_comparable(field_value)
    right = _coerce_comparable(target)
    try:
        if operator is FieldFilterOperator.GT:
            return bool(left > right)
        if operator is FieldFilterOperator.GTE:
            return bool(left >= right)
        if operator is FieldFilterOperator.LT:
            return bool(left < right)
        if operator is FieldFilterOperator.LTE:
            return bool(left <= right)
        right_to = _coerce_comparable(target_to)
        return bool(right <= left <= right_to)
    except TypeError:
        return False


class InMemoryDocumentSearchRepository:
    """Search over `InMemoryDocumentRepository`/`InMemoryDocumentExtractionRepository` state."""

    def __init__(
        self,
        document_repo: InMemoryDocumentRepository,
        extraction_repo: InMemoryDocumentExtractionRepository,
    ) -> None:
        self._documents = document_repo
        self._extractions = extraction_repo

    async def search(
        self,
        tenant: TenantContext,
        query: DocumentSearchQuery,
    ) -> DocumentSearchResult:
        candidates: list[DocumentRecord] = [
            document
            for (owner, _document_id), document in self._documents.documents.items()
            if owner == tenant.tenant_id
            and document.status is not DocumentLifecycleStatus.DELETED
        ]
        hits: list[DocumentSearchHit] = []
        for document in candidates:
            if not self._matches_metadata(document, query):
                continue
            matched_fields = self._matched_fields(tenant, document, query.field_filters)
            if query.field_filters and not matched_fields:
                continue
            hits.append(DocumentSearchHit(document=document, matched_fields=matched_fields))

        hits.sort(
            key=lambda hit: hit.document.updated_at
            or hit.document.created_at
            or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        total = len(hits)
        page = hits[query.offset : query.offset + query.limit]
        return DocumentSearchResult(items=page, total=total)

    def _matches_metadata(self, document: DocumentRecord, query: DocumentSearchQuery) -> bool:
        if query.text and query.text.casefold() not in (document.title or "").casefold():
            return False
        if query.document_type and document.document_type != query.document_type:
            return False
        if query.status and document.status.value != query.status:
            return False
        if query.tags and not set(query.tags) & set(document.tags):
            return False
        if query.department and document.department != query.department:
            return False
        if query.country and document.country != query.country:
            return False
        if query.business_unit and document.business_unit != query.business_unit:
            return False
        if query.classification and document.classification != query.classification:
            return False
        if query.created_after and (
            document.created_at is None or document.created_at < query.created_after
        ):
            return False
        return not (
            query.created_before
            and (document.created_at is None or document.created_at > query.created_before)
        )

    def _matched_fields(
        self,
        tenant: TenantContext,
        document: DocumentRecord,
        field_filters: list[FieldFilter],
    ) -> list[DocumentExtractedFieldRecord]:
        if not field_filters:
            return []
        runs = [
            run
            for (owner, _run_id), run in self._extractions.runs.items()
            if owner == tenant.tenant_id and run.document_id == document.document_id
        ]
        all_fields: list[DocumentExtractedFieldRecord] = []
        for run in runs:
            all_fields.extend(self._extractions.fields.get(run.run_id, []))

        matched: list[DocumentExtractedFieldRecord] = []
        for field_filter in field_filters:
            candidates = [field for field in all_fields if field.name == field_filter.name]
            satisfied = next(
                (
                    field
                    for field in candidates
                    if _matches_operator(
                        field.normalized_value
                        if field.normalized_value is not None
                        else field.value,
                        field_filter.operator,
                        field_filter.value,
                        field_filter.value_to,
                    )
                ),
                None,
            )
            if satisfied is None:
                return []
            matched.append(satisfied)
        return matched
