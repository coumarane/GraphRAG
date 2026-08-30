"""Document Intelligence model/field catalog API schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from graph_rag.application.document_intelligence.models import FieldType, ModelType
from graph_rag.domain.graph.vocabulary import SemanticNodeLabel, SemanticRelationshipType
from graph_rag.domain.types import JsonValue


class ModelFieldResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    field_type: FieldType
    default_selected: bool = False
    promote_to_document_metadata: bool = False


class FieldEntityMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: SemanticNodeLabel
    relationship_type: SemanticRelationshipType = SemanticRelationshipType.MENTIONS


class DocumentIntelligenceModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_key: str
    model_id: UUID | None = None
    name: str
    model_type: ModelType
    version: str
    is_builtin: bool
    fields: list[ModelFieldResponse] = Field(default_factory=list)
    field_entity_mappings: dict[str, FieldEntityMapping] = Field(default_factory=dict)
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
    promote_to_document_metadata: bool = False


class DocumentIntelligenceModelCreateRequest(BaseModel):
    """Create a custom model. ``model_type`` is always forced to CUSTOM server-side."""

    model_config = ConfigDict(extra="forbid")

    model_key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    fields: list[DocumentIntelligenceModelFieldCreateRequest] = Field(min_length=1)
    field_entity_mappings: dict[str, FieldEntityMapping] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _mappings_reference_real_fields(self) -> DocumentIntelligenceModelCreateRequest:
        field_names = {field.name for field in self.fields}
        unknown = set(self.field_entity_mappings) - field_names
        if unknown:
            raise ValueError(
                f"field_entity_mappings references unknown field(s): {sorted(unknown)}"
            )
        return self


class ExtractedFieldItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: JsonValue
    normalized_value: JsonValue | None = None
    confidence: float
    confidence_band: str
    page: int | None = None
    source_text: str | None = None
    extraction_method: str
    model_name: str | None = None


class DocumentExtractionRunItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    status: str
    model_key: str | None = None
    provider: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    fields: list[ExtractedFieldItem] = Field(default_factory=list)


class DocumentExtractionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DocumentExtractionRunItem]
