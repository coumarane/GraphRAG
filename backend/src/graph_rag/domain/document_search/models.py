"""Search across documents and their extracted structured fields."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from graph_rag.domain.document_intelligence.records import DocumentExtractedFieldRecord
from graph_rag.domain.ingestion.records import DocumentRecord
from graph_rag.domain.types import JsonValue


class FieldFilterOperator(StrEnum):
    """Comparison applied to one extracted field's value."""

    EQ = "eq"
    CONTAINS = "contains"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    BETWEEN = "between"


class FieldFilter(BaseModel):
    """One predicate on an extracted field.

    A document matches when it has an extracted field named ``name`` whose
    value satisfies ``operator`` against ``value`` (and ``value_to`` for
    ``between``). Multiple filters are ANDed, and each may be satisfied by a
    different field row -- a document doesn't need all filters resolved on
    the same extraction run.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    operator: FieldFilterOperator
    value: JsonValue
    value_to: JsonValue | None = None

    @model_validator(mode="after")
    def _require_value_to_for_between(self) -> FieldFilter:
        if self.operator is FieldFilterOperator.BETWEEN and self.value_to is None:
            raise ValueError("value_to is required for the 'between' operator")
        return self


class DocumentSearchQuery(BaseModel):
    """A structured document/field search request."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    document_type: str | None = None
    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    department: str | None = None
    country: str | None = None
    business_unit: str | None = None
    classification: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    field_filters: list[FieldFilter] = Field(default_factory=list)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class DocumentSearchHit(BaseModel):
    """One matched document plus the extracted fields that matched, if any."""

    model_config = ConfigDict(extra="forbid")

    document: DocumentRecord
    matched_fields: list[DocumentExtractedFieldRecord] = Field(default_factory=list)


class DocumentSearchResult(BaseModel):
    """Paginated search outcome."""

    model_config = ConfigDict(extra="forbid")

    items: list[DocumentSearchHit] = Field(default_factory=list)
    total: int = 0
