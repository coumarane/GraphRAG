"""Hierarchical multimodal chunk models."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.types import JsonValue


class ChunkType(StrEnum):
    """Chunk classification used by indexing and retrieval."""

    TEXT = "text"
    SECTION = "section"
    IMAGE = "image"
    CHART = "chart"
    TABLE = "table"
    TABLE_ROW = "table_row"
    EQUATION = "equation"
    MULTIMODAL_COMPOSITE = "multimodal_composite"
    DOCUMENT_SUMMARY = "document_summary"
    COMMUNITY_SUMMARY = "community_summary"


class ChunkBase(BaseModel):
    """Parent or child retrieval unit derived from normalized elements."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    parent_chunk_id: UUID | None = None
    modality: Modality
    chunk_type: ChunkType
    text: str
    token_count: int = Field(ge=0)
    element_ids: list[UUID] = Field(default_factory=list)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    section_path: list[str] = Field(default_factory=list)
    source_object_keys: list[str] = Field(default_factory=list)
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
    def _validate_page_range(self) -> ChunkBase:
        if self.page_end < self.page_start:
            msg = "page_end must be greater than or equal to page_start"
            raise ValueError(msg)
        return self
