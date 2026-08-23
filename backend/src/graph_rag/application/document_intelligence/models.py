"""Provider-agnostic Document Intelligence field/model schema types.

No extraction logic lives here (that starts in a later phase) -- this is
purely the shape of a model's field schema, shared by the built-in catalog
and by tenant-created custom models.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
