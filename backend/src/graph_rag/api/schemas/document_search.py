"""Document/field search API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.api.schemas.common import DocumentResponse
from graph_rag.api.schemas.document_intelligence import ExtractedFieldItem
from graph_rag.domain.types import JsonValue


class FieldFilterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    operator: Literal["eq", "contains", "gt", "gte", "lt", "lte", "between"]
    value: JsonValue
    value_to: JsonValue | None = None


class DocumentSearchRequest(BaseModel):
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
    field_filters: list[FieldFilterRequest] = Field(default_factory=list)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class DocumentSearchHitItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentResponse
    matched_fields: list[ExtractedFieldItem] = Field(default_factory=list)


class DocumentSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DocumentSearchHitItem]
    total: int
    offset: int
    limit: int
