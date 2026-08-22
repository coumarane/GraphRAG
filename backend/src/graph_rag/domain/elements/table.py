"""Table-specific structured representations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.types import JsonValue


class TableCell(BaseModel):
    """A single table cell with optional merged-cell spans."""

    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str = ""
    is_column_header: bool = False
    is_row_header: bool = False
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class TableData(BaseModel):
    """Structured table payload preserved alongside the element."""

    model_config = ConfigDict(extra="forbid")

    caption: str | None = None
    column_headers: list[str] = Field(default_factory=list)
    row_headers: list[str] = Field(default_factory=list)
    cells: list[TableCell] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    raw_parser_representation: dict[str, JsonValue] | None = None
    markdown: str | None = None
    semantic_summary: str | None = None
