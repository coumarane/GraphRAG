"""PostgreSQL document/field search repository.

Postgres-specific (JSONB scalar extraction, `websearch_to_tsquery` full-text
search on `documents.title`) -- there is no SQLite-compatible fallback, so
this repository's SQL correctness is not covered by this repo's usual
SQLite-backed "postgres repository" unit tests. See
``tests/unit/test_document_search_predicates.py`` for offline (no DB
connection) compiled-SQL assertions on the predicate-building helpers below,
and ``infrastructure.persistence.memory.document_search`` for the behavior
that *is* fully exercised through the route tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    TIMESTAMP,
    Numeric,
    and_,
    cast,
    func,
    literal_column,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from graph_rag.domain.document_search.models import (
    DocumentSearchHit,
    DocumentSearchQuery,
    DocumentSearchResult,
    FieldFilter,
    FieldFilterOperator,
)
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.postgres.mappers import (
    document_extracted_field_to_record,
    document_to_record,
)
from graph_rag.infrastructure.persistence.postgres.models import (
    DocumentExtractedFieldModel,
    DocumentExtractionRunModel,
    DocumentModel,
)
from graph_rag.infrastructure.persistence.postgres.rls import set_tenant_context


def _scalar_text(column: Any) -> Any:
    """Extract a JSONB scalar's text representation: ``value #>> '{}'``."""
    return column.op("#>>")(literal_column("'{}'"))


def _is_isoish_date(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _comparable_expr(column: Any, sample: Any) -> Any:
    """Cast a field's text value for ordered comparison, matching ``sample``'s shape.

    Numbers compare numerically; ISO-8601-looking date strings compare as
    timestamps; anything else compares as plain text. The cast is chosen
    from the *request's* value shape rather than the field's declared type,
    since ad-hoc/built-in fields aren't always backed by a model-field
    schema row to look a type up from.
    """
    text_expr = _scalar_text(column)
    if isinstance(sample, (int, float)) and not isinstance(sample, bool):
        return cast(text_expr, Numeric)
    if isinstance(sample, str) and _is_isoish_date(sample):
        return cast(text_expr, TIMESTAMP(timezone=True))
    return text_expr


def _comparable_operand(value: Any) -> Any:
    if isinstance(value, str) and _is_isoish_date(value) and not _looks_numeric(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _value_expr(field_model: type[DocumentExtractedFieldModel]) -> Any:
    return func.coalesce(field_model.normalized_value_json, field_model.value_json)


def field_filter_predicate(
    field_model: type[DocumentExtractedFieldModel],
    field_filter: FieldFilter,
) -> Any:
    """Build the WHERE predicate for one field filter against an (aliased) field row.

    Exposed at module level so it can be unit-tested by compiling it to SQL
    without a live database connection.
    """
    value_expr = _value_expr(field_model)
    operator = field_filter.operator
    if operator is FieldFilterOperator.EQ:
        predicate = func.lower(_scalar_text(value_expr)) == func.lower(str(field_filter.value))
    elif operator is FieldFilterOperator.CONTAINS:
        predicate = _scalar_text(value_expr).ilike(f"%{field_filter.value}%")
    else:
        left = _comparable_expr(value_expr, field_filter.value)
        right = _comparable_operand(field_filter.value)
        if operator is FieldFilterOperator.GT:
            predicate = left > right
        elif operator is FieldFilterOperator.GTE:
            predicate = left >= right
        elif operator is FieldFilterOperator.LT:
            predicate = left < right
        elif operator is FieldFilterOperator.LTE:
            predicate = left <= right
        else:  # BETWEEN
            right_to = _comparable_operand(field_filter.value_to)
            predicate = left.between(right, right_to)
    return and_(field_model.name == field_filter.name, predicate)


class SqlAlchemyDocumentSearchRepository:
    """SQLAlchemy implementation of ``DocumentSearchRepository``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        tenant: TenantContext,
        query: DocumentSearchQuery,
    ) -> DocumentSearchResult:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)

        clauses: list[Any] = [
            DocumentModel.tenant_id == tenant.tenant_id,
            DocumentModel.status != DocumentLifecycleStatus.DELETED.value,
        ]
        if query.text:
            # Expression must match the GIN index in migration 0012 exactly
            # (to_tsvector('simple', title)) for Postgres to use it.
            tsquery = func.websearch_to_tsquery("simple", query.text)
            fts_match = func.to_tsvector("simple", DocumentModel.title).op("@@")(tsquery)
            clauses.append(or_(fts_match, DocumentModel.title.ilike(f"%{query.text}%")))
        if query.document_type:
            clauses.append(DocumentModel.document_type == query.document_type)
        if query.status:
            clauses.append(DocumentModel.status == query.status)
        if query.tags:
            clauses.append(or_(*(DocumentModel.tags.contains([tag]) for tag in query.tags)))
        if query.department:
            clauses.append(DocumentModel.department == query.department)
        if query.country:
            clauses.append(DocumentModel.country == query.country)
        if query.business_unit:
            clauses.append(DocumentModel.business_unit == query.business_unit)
        if query.classification:
            clauses.append(DocumentModel.classification == query.classification)
        if query.created_after:
            clauses.append(DocumentModel.created_at >= query.created_after)
        if query.created_before:
            clauses.append(DocumentModel.created_at <= query.created_before)

        # One aliased (run, field) join pair per filter, so each filter can be
        # satisfied by a *different* extraction run/field row (AND across
        # filters, not "one row must satisfy every predicate at once"), and
        # so the matched field row is directly selectable for provenance.
        field_aliases = [aliased(DocumentExtractedFieldModel) for _ in query.field_filters]
        run_aliases = [aliased(DocumentExtractionRunModel) for _ in query.field_filters]

        statement = select(DocumentModel, *field_aliases).where(*clauses)
        for field_filter, field_alias, run_alias in zip(
            query.field_filters, field_aliases, run_aliases, strict=True
        ):
            statement = statement.join(
                run_alias,
                and_(
                    run_alias.document_id == DocumentModel.document_id,
                    run_alias.tenant_id == tenant.tenant_id,
                ),
            ).join(
                field_alias,
                and_(
                    field_alias.run_id == run_alias.run_id,
                    field_alias.tenant_id == tenant.tenant_id,
                    field_filter_predicate(field_alias, field_filter),
                ),
            )

        statement = (
            statement.order_by(DocumentModel.updated_at.desc().nullslast())
            .offset(query.offset)
            .limit(query.limit)
        )
        result = await self._session.execute(statement)
        rows = result.all()

        # DISTINCT document_id (a document can appear once per matching
        # combination of joined rows if multiple field rows independently
        # satisfy the same filter -- keep the first, richest match).
        seen: dict[Any, DocumentSearchHit] = {}
        for row in rows:
            document_model = row[0]
            document = document_to_record(document_model)
            if document.document_id in seen:
                continue
            matched_fields = [
                document_extracted_field_to_record(field_model)
                for field_model in row[1:]
                if field_model is not None
            ]
            seen[document.document_id] = DocumentSearchHit(
                document=document, matched_fields=matched_fields
            )

        count_statement = select(func.count(func.distinct(DocumentModel.document_id))).where(
            *clauses
        )
        for field_filter, field_alias, run_alias in zip(
            query.field_filters, field_aliases, run_aliases, strict=True
        ):
            count_statement = count_statement.join(
                run_alias,
                and_(
                    run_alias.document_id == DocumentModel.document_id,
                    run_alias.tenant_id == tenant.tenant_id,
                ),
            ).join(
                field_alias,
                and_(
                    field_alias.run_id == run_alias.run_id,
                    field_alias.tenant_id == tenant.tenant_id,
                    field_filter_predicate(field_alias, field_filter),
                ),
            )
        total = (await self._session.execute(count_statement)).scalar_one()

        return DocumentSearchResult(items=list(seen.values()), total=int(total))
