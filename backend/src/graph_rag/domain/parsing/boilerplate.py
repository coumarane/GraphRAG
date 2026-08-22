"""Repeated header/footer boilerplate detection for normalized documents."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.elements.models import (
    DocumentElement,
    PageFooterElement,
    PageHeaderElement,
    TextElement,
)
from graph_rag.domain.ids import content_sha256_hex

_SPACE_RE = re.compile(r"\s+")
_PAGE_NUM_RE = re.compile(
    r"(?i)^(?:page\s*)?\d+(?:\s*/\s*\d+)?$|^\d+\s*$|^[-–—]\s*\d+\s*[-–—]$"
)


def normalize_boilerplate_text(text: str) -> str:
    """Normalize text for cross-page boilerplate comparison."""
    folded = unicodedata.normalize("NFKC", text).casefold().strip()
    folded = _PAGE_NUM_RE.sub("<page>", folded)
    folded = _SPACE_RE.sub(" ", folded)
    return folded


@dataclass(frozen=True)
class BoilerplateMatch:
    """A text span detected as repeated page chrome."""

    normalized_text: str
    page_frequency: float
    page_count: int
    occurrence_count: int
    role: str  # header | footer | repeated


def detect_boilerplate(
    page_texts: Sequence[tuple[int, Sequence[str]]],
    *,
    min_pages: int = 3,
    frequency_threshold: float = 0.5,
    max_line_length: int = 160,
) -> list[BoilerplateMatch]:
    """Detect repeated top/bottom lines across pages.

    ``page_texts`` is a sequence of ``(page_number, lines)`` where lines are
    ordered top-to-bottom reading-order candidates.
    """
    usable = [(page, lines) for page, lines in page_texts if lines]
    if len(usable) < min_pages:
        return []

    top_counter: Counter[str] = Counter()
    bottom_counter: Counter[str] = Counter()
    any_counter: Counter[str] = Counter()
    pages_with_top: dict[str, set[int]] = {}
    pages_with_bottom: dict[str, set[int]] = {}
    pages_with_any: dict[str, set[int]] = {}

    for page_number, lines in usable:
        short_lines = [
            normalize_boilerplate_text(line)
            for line in lines
            if line.strip() and len(line.strip()) <= max_line_length
        ]
        short_lines = [line for line in short_lines if line and line != "<page>"]
        if not short_lines:
            continue
        top = short_lines[0]
        bottom = short_lines[-1]
        top_counter[top] += 1
        bottom_counter[bottom] += 1
        pages_with_top.setdefault(top, set()).add(page_number)
        pages_with_bottom.setdefault(bottom, set()).add(page_number)
        for line in short_lines:
            any_counter[line] += 1
            pages_with_any.setdefault(line, set()).add(page_number)

    page_total = len(usable)
    matches: list[BoilerplateMatch] = []
    seen: set[str] = set()

    def _maybe_add(text: str, pages: set[int], role: str, count: int) -> None:
        if text in seen:
            return
        freq = len(pages) / page_total
        if freq < frequency_threshold:
            return
        seen.add(text)
        matches.append(
            BoilerplateMatch(
                normalized_text=text,
                page_frequency=freq,
                page_count=page_total,
                occurrence_count=count,
                role=role,
            )
        )

    for text, count in top_counter.items():
        _maybe_add(text, pages_with_top.get(text, set()), "header", count)
    for text, count in bottom_counter.items():
        _maybe_add(text, pages_with_bottom.get(text, set()), "footer", count)
    for text, count in any_counter.items():
        pages = pages_with_any.get(text, set())
        if len(pages) / page_total >= max(frequency_threshold, 0.7):
            _maybe_add(text, pages, "repeated", count)

    return sorted(matches, key=lambda item: (-item.page_frequency, item.normalized_text))


def reclassify_boilerplate_elements(
    elements: Sequence[DocumentElement],
    *,
    min_pages: int = 3,
    frequency_threshold: float = 0.5,
) -> list[DocumentElement]:
    """Promote repeated chrome text elements to PAGE_HEADER / PAGE_FOOTER.

    Useful metadata is preserved on the element; downstream chunking already
    skips ``PAGE_HEADER`` / ``PAGE_FOOTER``.
    """
    by_page: dict[int, list[DocumentElement]] = {}
    for element in elements:
        by_page.setdefault(element.page_start, []).append(element)

    page_texts: list[tuple[int, list[str]]] = []
    for page_number in sorted(by_page):
        lines: list[str] = []
        for element in sorted(by_page[page_number], key=lambda item: item.reading_order):
            text = (element.normalized_content or element.raw_content or "").strip()
            if text:
                lines.append(text)
        page_texts.append((page_number, lines))

    matches = detect_boilerplate(
        page_texts,
        min_pages=min_pages,
        frequency_threshold=frequency_threshold,
    )
    if not matches:
        return list(elements)

    boilerplate_by_role: dict[str, set[str]] = {"header": set(), "footer": set(), "repeated": set()}
    for match in matches:
        boilerplate_by_role[match.role].add(match.normalized_text)

    rewritten: list[DocumentElement] = []
    for element in elements:
        if element.element_type in {ElementType.PAGE_HEADER, ElementType.PAGE_FOOTER}:
            rewritten.append(element)
            continue
        text = (element.normalized_content or element.raw_content or "").strip()
        if not text:
            rewritten.append(element)
            continue
        normalized = normalize_boilerplate_text(text)
        role: str | None = None
        if normalized in boilerplate_by_role["header"]:
            role = "header"
        elif normalized in boilerplate_by_role["footer"]:
            role = "footer"
        elif normalized in boilerplate_by_role["repeated"]:
            # Prefer footer for short trailing chrome; otherwise header.
            role = "footer" if len(text) <= 80 else "header"
        if role is None:
            rewritten.append(element)
            continue
        if not isinstance(element, TextElement):
            # Preserve non-text structured elements; mark metadata only.
            metadata = dict(element.metadata)
            metadata["boilerplate"] = True
            metadata["boilerplate_role"] = role
            rewritten.append(element.model_copy(update={"metadata": metadata}))
            continue

        common = {
            "element_id": element.element_id,
            "tenant_id": element.tenant_id,
            "document_id": element.document_id,
            "version_id": element.version_id,
            "page_start": element.page_start,
            "page_end": element.page_end,
            "bounding_boxes": list(element.bounding_boxes),
            "reading_order": element.reading_order,
            "section_path": list(element.section_path),
            "raw_content": element.raw_content,
            "normalized_content": element.normalized_content,
            "parser_confidence": element.parser_confidence,
            "ocr_confidence": element.ocr_confidence,
            "content_hash": element.content_hash
            or content_sha256_hex(text.encode("utf-8")),
            "metadata": {
                **dict(element.metadata),
                "boilerplate": True,
                "boilerplate_role": role,
                "promoted_from": element.element_type.value,
            },
        }
        if role == "footer":
            rewritten.append(PageFooterElement(**common))
        else:
            rewritten.append(PageHeaderElement(**common))
    return rewritten


def boilerplate_metadata_summary(matches: Sequence[BoilerplateMatch]) -> dict[str, object]:
    """Compact metadata payload for document-level storage."""
    return {
        "count": len(matches),
        "items": [
            {
                "text": match.normalized_text[:200],
                "role": match.role,
                "page_frequency": round(match.page_frequency, 3),
                "occurrence_count": match.occurrence_count,
            }
            for match in matches
        ],
    }
