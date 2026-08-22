"""Context window for multimodal element enrichment."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.types import JsonValue


class ElementContext(BaseModel):
    """Bounded surrounding context for interpreting a non-text element."""

    model_config = ConfigDict(extra="forbid")

    document_title: str | None = None
    document_type: str | None = None
    section_path: list[str] = Field(default_factory=list)
    heading: str | None = None
    caption: str | None = None
    preceding_text: str | None = None
    following_text: str | None = None
    nearby_element_summaries: list[str] = Field(default_factory=list)
    page_number: int = Field(ge=1)
    footnotes: list[str] = Field(default_factory=list)
    document_metadata: dict[str, JsonValue] = Field(default_factory=dict)
