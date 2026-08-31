"""Offline (no DB connection) compiled-SQL checks for the Postgres document
search predicate builder.

``SqlAlchemyDocumentSearchRepository`` uses Postgres-only JSONB/tsvector
operators that have no SQLite equivalent, so unlike this repo's other
"postgres repository" unit tests (which run against in-memory SQLite), the
query logic here is verified by compiling expressions to their target-dialect
SQL string and asserting on shape -- no live database required. End-to-end
behavior (filter semantics, multi-filter AND-across-different-rows, ABAC)
is covered instead through the fully-equivalent
``InMemoryDocumentSearchRepository`` via ``test_document_search_routes.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from graph_rag.domain.document_search.models import FieldFilter
from graph_rag.infrastructure.persistence.postgres.models import DocumentExtractedFieldModel
from graph_rag.infrastructure.persistence.postgres.repositories.document_search import (
    field_filter_predicate,
)


def _compiled(field_filter: FieldFilter) -> str:
    expr = field_filter_predicate(DocumentExtractedFieldModel, field_filter)
    return str(
        expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def test_eq_predicate_uses_case_insensitive_scalar_text_comparison() -> None:
    sql = _compiled(FieldFilter(name="lot_number", operator="eq", value="LOT-42"))
    assert "document_extracted_fields.name = 'lot_number'" in sql
    assert "#>> '{}'" in sql
    assert "lower(" in sql
    assert "'LOT-42'" in sql


def test_contains_predicate_uses_ilike() -> None:
    sql = _compiled(FieldFilter(name="abstract", operator="contains", value="polymer"))
    assert "ILIKE" in sql
    assert "%polymer%" in sql


def test_numeric_operator_casts_to_numeric() -> None:
    sql = _compiled(FieldFilter(name="purity_percentage", operator="gte", value=90))
    assert "CAST(" in sql and "AS NUMERIC)" in sql
    assert ">= 90" in sql


def test_date_like_string_casts_to_timestamp() -> None:
    sql = _compiled(FieldFilter(name="expiry_date", operator="lte", value="2024-12-31"))
    assert "AS TIMESTAMP WITH TIME ZONE)" in sql


def test_between_requires_both_bounds_and_casts_consistently() -> None:
    sql = _compiled(
        FieldFilter(
            name="expiry_date", operator="between", value="2024-01-01", value_to="2024-12-31"
        )
    )
    assert "BETWEEN" in sql
    assert "AS TIMESTAMP WITH TIME ZONE)" in sql


def test_between_without_value_to_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="value_to is required"):
        FieldFilter(name="expiry_date", operator="between", value="2024-01-01")


def test_non_numeric_non_date_string_falls_back_to_plain_text_comparison() -> None:
    sql = _compiled(FieldFilter(name="grade", operator="gt", value="Premium"))
    assert "CAST(" not in sql
    assert "#>> '{}'" in sql
    assert "> 'Premium'" in sql
