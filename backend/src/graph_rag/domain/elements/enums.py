"""Element type discriminator values matching ``contracts/normalized-document``."""

from __future__ import annotations

from enum import StrEnum


class ElementType(StrEnum):
    """Normalized multimodal element kinds."""

    TEXT = "text"
    HEADING = "heading"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"
    CHART = "chart"
    DIAGRAM = "diagram"
    EQUATION = "equation"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    CODE = "code"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
