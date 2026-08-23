"""Document Intelligence model/field catalog API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.application.document_intelligence.models import FieldType, ModelType


class ModelFieldResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    field_type: FieldType
    default_selected: bool = False


class DocumentIntelligenceModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_key: str
    model_id: UUID | None = None
    name: str
    model_type: ModelType
    version: str
    is_builtin: bool
    fields: list[ModelFieldResponse] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocumentIntelligenceModelListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DocumentIntelligenceModelResponse]


class DocumentIntelligenceModelFieldCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    field_type: FieldType
    default_selected: bool = False


class DocumentIntelligenceModelCreateRequest(BaseModel):
    """Create a custom model. ``model_type`` is always forced to CUSTOM server-side."""

    model_config = ConfigDict(extra="forbid")

    model_key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    fields: list[DocumentIntelligenceModelFieldCreateRequest] = Field(min_length=1)
