"""Shared fields for every normalized document element."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.elements.geometry import BoundingBox
from enterprise_rag.domain.types import JsonValue


class ElementBase(BaseModel):
    """Common provenance and layout fields for multimodal elements."""

    model_config = ConfigDict(extra="forbid")

    element_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    element_type: ElementType
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    reading_order: int = Field(ge=0)
    section_id: UUID | None = None
    section_path: list[str] = Field(default_factory=list)
    previous_element_id: UUID | None = None
    next_element_id: UUID | None = None
    nearby_element_ids: list[UUID] = Field(default_factory=list)
    caption_element_id: UUID | None = None
    source_asset_id: UUID | None = None
    raw_content: str | None = None
    normalized_content: str | None = None
    parser_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    content_hash: str = Field(min_length=64, max_length=64)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str) -> str:
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
            msg = "content_hash must be a 64-character lowercase hex SHA-256 digest"
            raise ValueError(msg)
        return value.lower()

    @model_validator(mode="after")
    def _validate_page_range(self) -> ElementBase:
        if self.page_end < self.page_start:
            msg = "page_end must be greater than or equal to page_start"
            raise ValueError(msg)
        return self
