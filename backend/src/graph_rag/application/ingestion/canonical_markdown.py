"""Derive Markdown from a CanonicalDocument. JSON remains authoritative."""

from __future__ import annotations

from graph_rag.domain.documents.document import NormalizedDocument
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.elements.models import HeadingElement, ListElement, TableElement
from graph_rag.domain.elements.table import TableData

_SKIP_TYPES = {ElementType.PAGE_HEADER, ElementType.PAGE_FOOTER}


def canonical_document_markdown(document: NormalizedDocument) -> str:
    """Best-effort Markdown projection of headings, tables, and paragraphs."""
    lines: list[str] = []
    if document.title:
        lines.append(f"# {document.title}")
        lines.append("")
    ordered = sorted(document.elements, key=lambda item: (item.page_start, item.reading_order))
    for element in ordered:
        if element.element_type in _SKIP_TYPES:
            continue
        if isinstance(element, HeadingElement):
            text = (element.normalized_content or element.raw_content or "").strip()
            if text:
                lines.append(f"{'#' * element.level} {text}")
                lines.append("")
            continue
        if isinstance(element, ListElement):
            items = element.items or []
            if not items:
                text = (element.normalized_content or element.raw_content or "").strip()
                if text:
                    lines.append(text)
                    lines.append("")
                continue
            marker = "1." if element.ordered else "-"
            for item in items:
                stripped = str(item).strip()
                if stripped:
                    lines.append(f"{marker} {stripped}")
            if items:
                lines.append("")
            continue
        if isinstance(element, TableElement):
            rendered = _table_to_markdown(element.table)
            if rendered:
                lines.append(rendered)
                lines.append("")
            continue
        text = (element.normalized_content or element.raw_content or "").strip()
        if text:
            lines.append(text)
            lines.append("")
    body = "\n".join(lines).strip()
    return body if body else document.source_filename


def _table_to_markdown(table: TableData) -> str:
    if table.markdown and table.markdown.strip():
        return table.markdown.strip()
    if not table.cells:
        return (table.caption or "").strip()
    max_row = max(cell.row_index for cell in table.cells)
    max_col = max(cell.column_index for cell in table.cells)
    grid = [[""] * (max_col + 1) for _ in range(max_row + 1)]
    for cell in table.cells:
        grid[cell.row_index][cell.column_index] = cell.text.replace("|", "\\|")
    header = grid[0]
    separator = ["---"] * len(header)
    rows = ["| " + " | ".join(header) + " |", "| " + " | ".join(separator) + " |"]
    for row in grid[1:]:
        rows.append("| " + " | ".join(row) + " |")
    if table.caption:
        return f"{table.caption}\n\n" + "\n".join(rows)
    return "\n".join(rows)
