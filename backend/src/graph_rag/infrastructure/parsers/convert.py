"""Convert adapter intermediate dict payloads into ``RawParserResult``."""

from __future__ import annotations

from typing import Any

from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.elements.geometry import BoundingBox
from graph_rag.domain.parsing.types import RawElement, RawPage, RawParserResult
from graph_rag.shared.exceptions import ParserError

_TYPE_MAP: dict[str, ElementType] = {
    "text": ElementType.TEXT,
    "paragraph": ElementType.TEXT,
    "heading": ElementType.HEADING,
    "title": ElementType.HEADING,
    "list": ElementType.LIST,
    "table": ElementType.TABLE,
    "image": ElementType.IMAGE,
    "figure": ElementType.IMAGE,
    "chart": ElementType.CHART,
    "diagram": ElementType.DIAGRAM,
    "equation": ElementType.EQUATION,
    "formula": ElementType.EQUATION,
    "caption": ElementType.CAPTION,
    "footnote": ElementType.FOOTNOTE,
    "code": ElementType.CODE,
    "page_header": ElementType.PAGE_HEADER,
    "header": ElementType.PAGE_HEADER,
    "page_footer": ElementType.PAGE_FOOTER,
    "footer": ElementType.PAGE_FOOTER,
}


def dict_to_raw_result(parser_name: str, payload: dict[str, Any]) -> RawParserResult:
    """Normalize heterogeneous adapter dicts into ``RawParserResult``."""
    elements_data = payload.get("elements", [])
    if not isinstance(elements_data, list):
        raise ParserError("Parser payload elements must be a list")

    elements: list[RawElement] = []
    for index, item in enumerate(elements_data):
        if not isinstance(item, dict):
            raise ParserError("Parser element payload must be an object")
        type_name = str(item.get("type", "text")).lower()
        element_type = _TYPE_MAP.get(type_name, ElementType.TEXT)
        page = int(item.get("page", item.get("page_start", 1)) or 1)
        page_end = int(item.get("page_end", page) or page)
        text = item.get("text") or item.get("content") or ""
        metadata = dict(item.get("metadata") or {})
        if "level" in item:
            metadata["level"] = item["level"]
        if "latex" in item:
            metadata["latex"] = item["latex"]
        if "items" in item:
            metadata["items"] = item["items"]
        elements.append(
            RawElement(
                element_type=element_type,
                page_start=max(1, page),
                page_end=max(1, page_end),
                reading_order=int(item.get("reading_order", index)),
                section_path=[str(part) for part in item.get("section_path", [])],
                raw_content=str(text) if text is not None else None,
                normalized_content=str(text) if text is not None else None,
                parser_confidence=_as_float(item.get("confidence")),
                ocr_confidence=_as_float(item.get("ocr_confidence")),
                metadata=metadata,
                bounding_boxes=_bbox_list(item.get("bbox")),
            )
        )

    page_count = int(payload.get("page_count") or 0)
    if page_count <= 0:
        page_count = max((element.page_end for element in elements), default=0)

    pages_data = payload.get("pages")
    pages: list[RawPage] = []
    if isinstance(pages_data, list):
        for item in pages_data:
            if isinstance(item, dict):
                pages.append(
                    RawPage(
                        page_number=int(item.get("page_number", 1)),
                        width=_as_float(item.get("width")),
                        height=_as_float(item.get("height")),
                        text_density=_as_float(item.get("text_density")),
                        image_coverage=_as_float(item.get("image_coverage")),
                        is_scanned=bool(item["is_scanned"]) if "is_scanned" in item else None,
                    )
                )
    if not pages and page_count:
        pages = [RawPage(page_number=number) for number in range(1, page_count + 1)]

    warnings = payload.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    return RawParserResult(
        parser_name=parser_name,
        parser_version=str(payload["parser_version"]) if payload.get("parser_version") else None,
        title=str(payload["title"]) if payload.get("title") is not None else None,
        language=str(payload["language"]) if payload.get("language") is not None else None,
        page_count=page_count,
        pages=pages,
        elements=elements,
        warnings=[str(item) for item in warnings],
        metadata=dict(payload.get("metadata") or {}),
    )


def _bbox_list(value: object) -> list[BoundingBox]:
    if not isinstance(value, dict):
        return []
    try:
        return [
            BoundingBox(
                page_number=int(value["page_number"]),
                x0=float(value["x0"]),
                y0=float(value["y0"]),
                x1=float(value["x1"]),
                y1=float(value["y1"]),
            )
        ]
    except (KeyError, TypeError, ValueError):
        return []


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
