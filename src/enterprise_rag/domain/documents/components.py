"""Supporting structures for the normalized multimodal document."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.domain.types import JsonValue


class NormalizedPage(BaseModel):
    """Page-level metadata within a normalized document."""

    model_config = ConfigDict(extra="forbid")

    page_id: UUID
    page_number: int = Field(ge=1)
    width: float | None = None
    height: float | None = None
    text_density: float | None = Field(default=None, ge=0.0)
    image_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    is_scanned: bool | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class DocumentSection(BaseModel):
    """Logical section in the document hierarchy."""

    model_config = ConfigDict(extra="forbid")

    section_id: UUID
    title: str | None = None
    level: int = Field(default=1, ge=1, le=9)
    path: list[str] = Field(default_factory=list)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    parent_section_id: UUID | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class DocumentAsset(BaseModel):
    """Binary asset extracted or rendered from the document."""

    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    asset_type: str
    mime_type: str
    object_key: str
    page_number: int | None = Field(default=None, ge=1)
    element_id: UUID | None = None
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)
    byte_size: int | None = Field(default=None, ge=0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ElementReference(BaseModel):
    """Cross-reference between elements (caption, footnote, citation)."""

    model_config = ConfigDict(extra="forbid")

    reference_id: UUID
    source_element_id: UUID
    target_element_id: UUID
    reference_type: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ParserInfo(BaseModel):
    """Parser provenance for a normalized document."""

    model_config = ConfigDict(extra="forbid")

    parser_name: str
    parser_version: str | None = None
    profile: str | None = None
    attempted_parsers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
