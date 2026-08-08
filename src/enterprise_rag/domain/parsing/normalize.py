"""Convert ``RawParserResult`` into ``NormalizedDocument``."""

from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from enterprise_rag.domain.documents.components import (
    DocumentSection,
    NormalizedPage,
    ParserInfo,
)
from enterprise_rag.domain.documents.document import NormalizedDocument
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.elements.geometry import BoundingBox
from enterprise_rag.domain.elements.models import (
    CaptionElement,
    ChartElement,
    CodeElement,
    DiagramElement,
    DocumentElement,
    EquationElement,
    FootnoteElement,
    HeadingElement,
    ImageElement,
    ListElement,
    PageFooterElement,
    PageHeaderElement,
    TableElement,
    TextElement,
)
from enterprise_rag.domain.elements.table import TableData
from enterprise_rag.domain.ids import content_sha256_hex, deterministic_id, new_id
from enterprise_rag.domain.parsing.types import ParseSource, RawElement, RawParserResult
from enterprise_rag.domain.storage.limits import assert_within_page_limit
from enterprise_rag.domain.types import JsonValue
from enterprise_rag.shared.exceptions import ParserError, ValidationError


class _CommonElementFields(TypedDict):
    element_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    page_start: int
    page_end: int
    bounding_boxes: list[BoundingBox]
    reading_order: int
    section_path: list[str]
    raw_content: str | None
    normalized_content: str | None
    parser_confidence: float | None
    ocr_confidence: float | None
    content_hash: str
    metadata: dict[str, JsonValue]


def normalize_parser_result(
    raw: RawParserResult,
    source: ParseSource,
    *,
    max_pages: int = 2_000,
) -> NormalizedDocument:
    """Normalize parser output into the application document model."""
    if not raw.parser_name:
        raise ValidationError("RawParserResult.parser_name is required")

    pages = [
        NormalizedPage(
            page_id=deterministic_id(
                str(source.tenant_id),
                str(source.document_id),
                str(source.version_id),
                f"page:{page.page_number}",
            ),
            page_number=page.page_number,
            width=page.width,
            height=page.height,
            text_density=page.text_density,
            image_coverage=page.image_coverage,
            is_scanned=page.is_scanned,
            metadata=dict(page.metadata),
        )
        for page in raw.pages
    ]
    if not pages and raw.page_count > 0:
        pages = [
            NormalizedPage(
                page_id=deterministic_id(
                    str(source.tenant_id),
                    str(source.document_id),
                    str(source.version_id),
                    f"page:{number}",
                ),
                page_number=number,
            )
            for number in range(1, raw.page_count + 1)
        ]

    elements = [
        _normalize_element(raw_element, source, index)
        for index, raw_element in enumerate(raw.elements)
    ]
    from enterprise_rag.domain.parsing.boilerplate import (
        boilerplate_metadata_summary,
        detect_boilerplate,
        reclassify_boilerplate_elements,
    )

    page_lines: list[tuple[int, list[str]]] = []
    by_page: dict[int, list[str]] = {}
    for element in elements:
        text = (element.normalized_content or element.raw_content or "").strip()
        if text:
            by_page.setdefault(element.page_start, []).append(text)
    for page_number in sorted(by_page):
        page_lines.append((page_number, by_page[page_number]))
    boilerplate_matches = detect_boilerplate(page_lines)
    elements = reclassify_boilerplate_elements(elements)
    _link_neighbors(elements)
    sections = _build_sections(elements, source)

    page_count = raw.page_count if raw.page_count else len(pages)
    assert_within_page_limit(page_count, max_pages=max_pages)
    metadata = dict(raw.metadata)
    if boilerplate_matches:
        metadata["boilerplate"] = boilerplate_metadata_summary(boilerplate_matches)
    return NormalizedDocument(
        tenant_id=source.tenant_id,
        document_id=source.document_id,
        version_id=source.version_id,
        title=raw.title,
        source_filename=source.filename,
        mime_type=source.mime_type,
        language=raw.language,
        page_count=page_count,
        metadata=metadata,
        pages=pages,
        elements=elements,
        sections=sections,
        assets=[],
        references=[],
        parser_info=ParserInfo(
            parser_name=raw.parser_name,
            parser_version=raw.parser_version,
            warnings=list(raw.warnings),
            metadata={"source_mime_type": source.mime_type},
        ),
    )


def _normalize_element(
    raw: RawElement,
    source: ParseSource,
    index: int,
) -> DocumentElement:
    if raw.page_end < raw.page_start:
        raise ParserError(
            "Raw element page range is invalid",
            details={"page_start": raw.page_start, "page_end": raw.page_end},
        )
    text = raw.normalized_content or raw.raw_content or ""
    content_hash = content_sha256_hex(
        f"{raw.element_type.value}|{raw.page_start}|{raw.reading_order}|{text}"
    )
    element_id = deterministic_id(
        str(source.tenant_id),
        str(source.document_id),
        str(source.version_id),
        f"element:{raw.page_start}:{raw.reading_order}:{content_hash[:16]}",
    )
    common: _CommonElementFields = {
        "element_id": element_id,
        "tenant_id": source.tenant_id,
        "document_id": source.document_id,
        "version_id": source.version_id,
        "page_start": raw.page_start,
        "page_end": raw.page_end,
        "bounding_boxes": list(raw.bounding_boxes),
        "reading_order": raw.reading_order if raw.reading_order >= 0 else index,
        "section_path": list(raw.section_path),
        "raw_content": raw.raw_content,
        "normalized_content": raw.normalized_content or raw.raw_content,
        "parser_confidence": raw.parser_confidence,
        "ocr_confidence": raw.ocr_confidence,
        "content_hash": content_hash,
        "metadata": dict(raw.metadata),
    }

    element_type = raw.element_type
    if element_type is ElementType.TEXT:
        return TextElement(**common)
    if element_type is ElementType.HEADING:
        level = _meta_int(raw, "level", default=1)
        return HeadingElement(**common, level=max(1, min(level, 9)))
    if element_type is ElementType.LIST:
        items = raw.metadata.get("items")
        item_list = [str(item) for item in items] if isinstance(items, list) else []
        ordered = bool(raw.metadata.get("ordered", False))
        return ListElement(**common, ordered=ordered, items=item_list)
    if element_type is ElementType.TABLE:
        return TableElement(
            **common,
            table=TableData(
                markdown=text or None,
                caption=_meta_str(raw, "caption"),
            ),
        )
    if element_type is ElementType.IMAGE:
        return ImageElement(
            **common,
            visual_description=_meta_str(raw, "visual_description"),
            ocr_text=_meta_str(raw, "ocr_text"),
        )
    if element_type is ElementType.CHART:
        legend_raw = raw.metadata.get("legend")
        legend = (
            [str(item) for item in legend_raw if str(item).strip()]
            if isinstance(legend_raw, list)
            else []
        )
        trends_raw = raw.metadata.get("trends")
        trends = (
            [str(item) for item in trends_raw if str(item).strip()]
            if isinstance(trends_raw, list)
            else []
        )
        axes_raw = raw.metadata.get("axes")
        axes: dict[str, object] = {}
        if isinstance(axes_raw, dict):
            for key, value in axes_raw.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    axes[str(key)] = value
                else:
                    axes[str(key)] = str(value)
        return ChartElement(
            **common,
            chart_type=_meta_str(raw, "chart_type"),
            title=_meta_str(raw, "title"),
            axes=axes,  # type: ignore[arg-type]
            legend=legend,
            trends=trends,
            visual_description=_meta_str(raw, "visual_description"),
            ocr_text=_meta_str(raw, "ocr_text"),
        )
    if element_type is ElementType.DIAGRAM:
        return DiagramElement(
            **common,
            visual_description=_meta_str(raw, "visual_description"),
            ocr_text=_meta_str(raw, "ocr_text"),
        )
    if element_type is ElementType.EQUATION:
        return EquationElement(
            **common,
            latex=_meta_str(raw, "latex"),
            mathml=_meta_str(raw, "mathml"),
            semantic_description=_meta_str(raw, "semantic_description"),
        )
    if element_type is ElementType.CAPTION:
        return CaptionElement(**common)
    if element_type is ElementType.FOOTNOTE:
        return FootnoteElement(**common, marker=_meta_str(raw, "marker"))
    if element_type is ElementType.CODE:
        return CodeElement(**common, language=_meta_str(raw, "language"))
    if element_type is ElementType.PAGE_HEADER:
        return PageHeaderElement(**common)
    if element_type is ElementType.PAGE_FOOTER:
        return PageFooterElement(**common)
    raise ParserError(
        "Unsupported raw element type",
        details={"element_type": element_type.value},
    )


def _meta_str(raw: RawElement, key: str) -> str | None:
    value = raw.metadata.get(key)
    return str(value) if value is not None else None


def _meta_int(raw: RawElement, key: str, *, default: int) -> int:
    value = raw.metadata.get(key, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _link_neighbors(elements: list[DocumentElement]) -> None:
    ordered = sorted(
        range(len(elements)),
        key=lambda i: (elements[i].page_start, elements[i].reading_order),
    )
    linked: list[DocumentElement] = list(elements)
    for position, index in enumerate(ordered):
        previous_id = (
            elements[ordered[position - 1]].element_id if position > 0 else None
        )
        next_id = (
            elements[ordered[position + 1]].element_id
            if position + 1 < len(ordered)
            else None
        )
        linked[index] = elements[index].model_copy(
            update={
                "previous_element_id": previous_id,
                "next_element_id": next_id,
            }
        )
    elements[:] = linked


def _build_sections(
    elements: list[DocumentElement],
    source: ParseSource,
) -> list[DocumentSection]:
    sections: list[DocumentSection] = []
    seen: set[tuple[str, ...]] = set()
    for element in elements:
        path = tuple(element.section_path)
        if not path or path in seen:
            continue
        seen.add(path)
        sections.append(
            DocumentSection(
                section_id=deterministic_id(
                    str(source.tenant_id),
                    str(source.document_id),
                    str(source.version_id),
                    "section:" + "/".join(path),
                ),
                title=path[-1],
                level=len(path),
                path=list(path),
                page_start=element.page_start,
                page_end=element.page_end,
            )
        )
    return sections


def empty_parse_source(
    *,
    tenant_id: UUID | None = None,
    document_id: UUID | None = None,
    version_id: UUID | None = None,
    filename: str = "document.bin",
    mime_type: str = "application/octet-stream",
    content: bytes = b"",
) -> ParseSource:
    """Helper for tests and adapters needing identity fields."""
    return ParseSource(
        tenant_id=tenant_id or new_id(),
        document_id=document_id or new_id(),
        version_id=version_id or new_id(),
        filename=filename,
        mime_type=mime_type,
        content=content,
    )
