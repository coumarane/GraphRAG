"""Parser request/response domain types."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.elements.geometry import BoundingBox
from graph_rag.domain.types import JsonValue


class ParserName(StrEnum):
    """Convenience aliases for first-party parser names.

    Routing and overrides accept any registered string key. These members are
    not a closed gate for third-party parsers.
    """

    AUTO = "auto"
    DOCLING = "docling"
    MINERU = "mineru"
    MARKER = "marker"
    PADDLEOCR = "paddleocr"
    PDFIUM = "pdfium"
    TEXT = "text"


def parser_key(name: ParserName | str) -> str:
    """Normalize a parser name or enum member to a lowercase registry key."""
    value = name.value if isinstance(name, ParserName) else str(name)
    return value.strip().lower()


class ParserProfile(StrEnum):
    """Parser routing profiles."""

    FAST = "fast"
    BALANCED = "balanced"
    ACCURATE = "accurate"
    SCIENTIFIC = "scientific"
    SCANNED = "scanned"


class OcrMode(StrEnum):
    """OCR execution policy for parse options."""

    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


class ParseSource(BaseModel):
    """Input document bytes/path for inspection or parsing."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    filename: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    content: bytes | None = None
    path: Path | None = None
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)

    def require_bytes(self) -> bytes:
        if self.content is not None:
            return self.content
        if self.path is not None:
            return self.path.read_bytes()
        msg = "ParseSource requires content bytes or a readable path"
        raise ValueError(msg)


class ParseOptions(BaseModel):
    """Options controlling parser/OCR behaviour."""

    model_config = ConfigDict(extra="forbid")

    profile: ParserProfile = ParserProfile.BALANCED
    parser_override: ParserName | str | None = None
    ocr_mode: OcrMode = OcrMode.AUTO
    ocr_language: str = "en"
    ocr_min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    failure_mode: str = "fallback"
    fallback_parsers: list[ParserName | str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class PageInspection(BaseModel):
    """Per-page inspection metrics from PDFium."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    width: float | None = None
    height: float | None = None
    extractable_chars: int = Field(default=0, ge=0)
    image_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    is_scanned_candidate: bool = False


class ParserInspection(BaseModel):
    """Document inspection used for parser routing."""

    model_config = ConfigDict(extra="forbid")

    mime_type: str
    page_count: int = Field(ge=0)
    file_size_bytes: int = Field(ge=0)
    pages: list[PageInspection] = Field(default_factory=list)
    extractable_chars_per_page: list[int] = Field(default_factory=list)
    mean_chars_per_page: float = 0.0
    scanned_page_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    image_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    probable_table_density: float = Field(default=0.0, ge=0.0, le=1.0)
    probable_formula_density: float = Field(default=0.0, ge=0.0, le=1.0)
    column_count_estimate: int | None = Field(default=None, ge=1)
    detected_language: str | None = None
    recommended_profile: ParserProfile = ParserProfile.BALANCED
    recommended_parser: str = ParserName.DOCLING.value
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RawElement(BaseModel):
    """Parser-native element prior to normalization."""

    model_config = ConfigDict(extra="forbid")

    element_type: ElementType
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    reading_order: int = Field(ge=0)
    section_path: list[str] = Field(default_factory=list)
    raw_content: str | None = None
    normalized_content: str | None = None
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    parser_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RawPage(BaseModel):
    """Parser-native page summary."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    width: float | None = None
    height: float | None = None
    text_density: float | None = None
    image_coverage: float | None = None
    is_scanned: bool | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RawParserResult(BaseModel):
    """Untyped parser output converted into ``NormalizedDocument``."""

    model_config = ConfigDict(extra="forbid")

    parser_name: str
    parser_version: str | None = None
    title: str | None = None
    language: str | None = None
    page_count: int = Field(ge=0)
    pages: list[RawPage] = Field(default_factory=list)
    elements: list[RawElement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ParserSelection(BaseModel):
    """Result of automatic or explicit parser routing."""

    model_config = ConfigDict(extra="forbid")

    primary: str
    fallbacks: list[str] = Field(default_factory=list)
    profile: ParserProfile
    reason: str
    inspection: ParserInspection | None = None
