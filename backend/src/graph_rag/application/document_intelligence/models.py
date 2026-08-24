"""Provider-agnostic Document Intelligence field/model schema types.

No extraction logic lives here (that starts in a later phase) -- this is
purely the shape of a model's field schema, shared by the built-in catalog
and by tenant-created custom models.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.documents.document import NormalizedDocument
from graph_rag.domain.elements.geometry import BoundingBox
from graph_rag.domain.parsing.types import RawParserResult
from graph_rag.domain.types import JsonValue


class FieldType(StrEnum):
    """Value shape of one extracted/extractable field."""

    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    LIST = "list"
    OBJECT = "object"
    TABLE = "table"


class ModelType(StrEnum):
    """Where a model's field schema came from."""

    PREBUILT = "prebuilt"
    CUSTOM = "custom"
    AD_HOC = "ad_hoc"


class ModelFieldSpec(BaseModel):
    """One field in a model's schema."""

    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    field_type: FieldType
    default_selected: bool = False
    promote_to_document_metadata: bool = False


class DocumentIntelligenceModel(BaseModel):
    """A model available for extraction: a built-in, or a tenant's custom one.

    ``model_key`` is the stable identifier callers select by (works for both
    built-ins and custom models); ``model_id`` is only set for a persisted
    custom model, since built-ins are static data with no database row.
    """

    model_config = ConfigDict(extra="forbid")

    model_key: str
    model_id: UUID | None = None
    name: str
    model_type: ModelType
    version: str = "1.0"
    is_builtin: bool = False
    fields: list[ModelFieldSpec] = Field(default_factory=list)


class DocumentIntelligenceIngestOptions(BaseModel):
    """Per-upload extraction request, carried in ``IngestionRunRecord.metadata``.

    Phase 3 only threads this through to storage -- the always-skip stub
    stage does not read it yet. ``enabled=False`` (the default) is what an
    upload that never sends this block looks like once parsed.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    model_id: str | None = None
    selected_fields: list[str] | None = None
    custom_fields: list[ModelFieldSpec] | None = None


class ConfidenceBand(StrEnum):
    """Coarse confidence tier surfaced to callers, independent of provider."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


def confidence_band(value: float) -> ConfidenceBand:
    if value >= 0.90:
        return ConfidenceBand.HIGH
    if value >= 0.70:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


class ExtractionMethod(StrEnum):
    """How one field's value was produced."""

    STRUCTURED_PARSER = "STRUCTURED_PARSER"
    RULES = "RULES"
    TABLE_EXTRACTION = "TABLE_EXTRACTION"
    EMBEDDING_SEMANTIC = "EMBEDDING_SEMANTIC"
    LLM = "LLM"
    VISION = "VISION"


class DocumentExtractionRunStatus(StrEnum):
    """Vocabulary for the ``document_extraction_runs.status`` column."""

    PENDING = "pending"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class ExtractedFieldResult(BaseModel):
    """One field's extracted value, with full provenance.

    No confidence floor exists anywhere on this type or in how it's produced
    -- a low-confidence result is a valid ``ExtractedFieldResult``, never
    filtered. Only a field with zero candidates across every tier is omitted
    from a result entirely (there's no way to represent "no value" as a row
    anyway -- the persisted ``value_json`` column is ``NOT NULL``).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    value: JsonValue
    normalized_value: JsonValue | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: ConfidenceBand
    extraction_method: ExtractionMethod
    page: int | None = None
    source_text: str | None = None
    bounding_box: BoundingBox | None = None
    model_name: str | None = None


class DocumentIntelligenceExtractionRequest(BaseModel):
    """Input to a provider's extraction chain.

    Named with the ``DocumentIntelligence`` prefix rather than a bare
    ``ExtractionRequest`` -- ``graph_rag.domain.models.contracts
    .ExtractionRequest`` already exists for the unrelated LLM-based
    ``StructuredExtractor``, and a same-name/different-shape type here would
    be a landmine for anyone importing both.
    """

    model_config = ConfigDict(extra="forbid")

    document: NormalizedDocument
    fields: list[ModelFieldSpec] = Field(min_length=1)
    model_name: str | None = None
    raw_parser_result: RawParserResult | None = None
    document_bytes: bytes | None = None


class DocumentIntelligenceExtractionResult(BaseModel):
    """Output of a provider's extraction chain for one document."""

    model_config = ConfigDict(extra="forbid")

    fields: list[ExtractedFieldResult] = Field(default_factory=list)
    requested_field_names: list[str] = Field(default_factory=list)
    unresolved_field_names: list[str] = Field(default_factory=list)
