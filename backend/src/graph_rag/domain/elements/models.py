"""Discriminated multimodal document element union."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.elements.base import ElementBase
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.elements.table import TableData
from graph_rag.domain.types import JsonValue


class TextElement(ElementBase):
    """Body text paragraph or span."""

    element_type: Literal[ElementType.TEXT] = ElementType.TEXT


class HeadingElement(ElementBase):
    """Section heading with hierarchy level."""

    element_type: Literal[ElementType.HEADING] = ElementType.HEADING
    level: int = Field(default=1, ge=1, le=9)


class ListElement(ElementBase):
    """Ordered or unordered list."""

    element_type: Literal[ElementType.LIST] = ElementType.LIST
    ordered: bool = False
    items: list[str] = Field(default_factory=list)


class TableElement(ElementBase):
    """Structured table with cells, headers and optional summary."""

    element_type: Literal[ElementType.TABLE] = ElementType.TABLE
    table: TableData = Field(default_factory=TableData)


class ImageElement(ElementBase):
    """Raster or embedded image with optional vision enrichment."""

    element_type: Literal[ElementType.IMAGE] = ElementType.IMAGE
    visual_description: str | None = None
    ocr_text: str | None = None
    model_provenance: dict[str, JsonValue] = Field(default_factory=dict)


class ChartElement(ElementBase):
    """Chart or plot with structured extraction fields."""

    element_type: Literal[ElementType.CHART] = ElementType.CHART
    chart_type: str | None = None
    title: str | None = None
    axes: dict[str, JsonValue] = Field(default_factory=dict)
    legend: list[str] = Field(default_factory=list)
    series: list[dict[str, JsonValue]] = Field(default_factory=list)
    visual_description: str | None = None
    ocr_text: str | None = None
    trends: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    model_provenance: dict[str, JsonValue] = Field(default_factory=dict)


class DiagramElement(ElementBase):
    """Diagram or schematic figure."""

    element_type: Literal[ElementType.DIAGRAM] = ElementType.DIAGRAM
    visual_description: str | None = None
    ocr_text: str | None = None
    model_provenance: dict[str, JsonValue] = Field(default_factory=dict)


class EquationVariable(BaseModel):
    """Symbol appearing in an equation."""

    model_config = ConfigDict(extra="forbid")

    name: str
    definition: str | None = None


class EquationElement(ElementBase):
    """Mathematical equation with optional LaTeX/MathML."""

    element_type: Literal[ElementType.EQUATION] = ElementType.EQUATION
    latex: str | None = None
    mathml: str | None = None
    variables: list[EquationVariable] = Field(default_factory=list)
    contextual_explanation: str | None = None
    semantic_description: str | None = None
    model_provenance: dict[str, JsonValue] = Field(default_factory=dict)


class CaptionElement(ElementBase):
    """Caption associated with a figure, table or equation."""

    element_type: Literal[ElementType.CAPTION] = ElementType.CAPTION
    target_element_id: UUID | None = None


class FootnoteElement(ElementBase):
    """Footnote or endnote."""

    element_type: Literal[ElementType.FOOTNOTE] = ElementType.FOOTNOTE
    marker: str | None = None


class CodeElement(ElementBase):
    """Source code or monospace block."""

    element_type: Literal[ElementType.CODE] = ElementType.CODE
    language: str | None = None


class PageHeaderElement(ElementBase):
    """Repeated page header."""

    element_type: Literal[ElementType.PAGE_HEADER] = ElementType.PAGE_HEADER


class PageFooterElement(ElementBase):
    """Repeated page footer."""

    element_type: Literal[ElementType.PAGE_FOOTER] = ElementType.PAGE_FOOTER


DocumentElement = Annotated[
    TextElement
    | HeadingElement
    | ListElement
    | TableElement
    | ImageElement
    | ChartElement
    | DiagramElement
    | EquationElement
    | CaptionElement
    | FootnoteElement
    | CodeElement
    | PageHeaderElement
    | PageFooterElement,
    Field(discriminator="element_type"),
]
