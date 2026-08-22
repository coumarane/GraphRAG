"""pypdfium2 text/layout extractor used as a reliable fallback parser."""

from __future__ import annotations

import re

from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.parsing.types import RawElement, RawPage, RawParserResult
from graph_rag.domain.retrieval.condition_facets import (
    extract_condition_facets,
    merge_facets,
    prose_for_facets,
)
from graph_rag.shared.exceptions import ValidationError

_TABLE_HINT = re.compile(
    r"(?i)\b(size|surface|area|inci|cas|specification|item|unit|value|μm|um\b|㎡|mg|%|wt)\b"
)
_EQUATION_HINT = re.compile(
    r"(\u03b1-|\u03b2-|\u03b3-|Al2O3|Al\u2082O\u2083|SiO2|TiO2|"
    r"\u2192|\u21cc|\u2248|\u2264|\u2265|\u221a|\u2211|\u222b|"
    r"[A-Za-z]+\d+[A-Za-z0-9]*)"
)


def classify_text_block(text: str) -> ElementType:
    """Heuristic element typing for plain extracted PDF text blocks."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ElementType.TEXT
    if len(lines) == 1 and len(lines[0]) <= 80 and not lines[0].endswith("."):
        words = lines[0].split()
        if 1 <= len(words) <= 10 and not _EQUATION_HINT.search(lines[0]):
            return ElementType.HEADING
    numeric_lines = sum(
        1 for line in lines if sum(ch.isdigit() for ch in line) >= 2 and _TABLE_HINT.search(line)
    )
    if len(lines) >= 2 and numeric_lines >= max(2, len(lines) // 2):
        return ElementType.TABLE
    if _EQUATION_HINT.search(text) and len(text) < 240:
        return ElementType.EQUATION
    return ElementType.TEXT


def split_page_blocks(text: str) -> list[str]:
    """Split page text into element-sized blocks without collapsing single-newline pages."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    blocks = [block.strip() for block in normalized.split("\n\n") if block.strip()]
    if len(blocks) <= 1:
        line_blocks = [block.strip() for block in normalized.split("\n") if block.strip()]
        if len(line_blocks) > 1:
            blocks = line_blocks
    return blocks or [normalized]


def extract_pdf_raw(data: bytes, *, filename: str, max_pages: int) -> RawParserResult:
    """Extract text-native PDF content with pypdfium2."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        page_count = len(document)
        limit = min(page_count, max_pages)
        elements: list[RawElement] = []
        pages: list[RawPage] = []
        page_texts: dict[int, str] = {}
        order = 0
        for index in range(limit):
            page = document[index]
            width, height = page.get_size()
            text_page = page.get_textpage()
            try:
                text = (text_page.get_text_bounded() or "").strip()
            finally:
                text_page.close()
            page.close()
            page_number = index + 1
            page_texts[page_number] = text
            coverage = 0.9 if len(text) < 80 else 0.15
            pages.append(
                RawPage(
                    page_number=page_number,
                    width=float(width),
                    height=float(height),
                    text_density=float(len(text)),
                    image_coverage=coverage,
                    is_scanned=len(text) < 40,
                )
            )
            if coverage >= 0.5:
                # Sparse/native-image pages: emit an image marker for hybrid vision.
                elements.append(
                    RawElement(
                        element_type=ElementType.IMAGE,
                        page_start=page_number,
                        page_end=page_number,
                        reading_order=order,
                        section_path=[f"Page {page_number}"],
                        raw_content=None,
                        normalized_content=None,
                        metadata={"source": "pdfium_sparse_page"},
                    )
                )
                order += 1
            if not text:
                continue
            page_facets = extract_condition_facets(text)
            page_prose = prose_for_facets(page_facets)
            for block in split_page_blocks(text):
                element_type = classify_text_block(block)
                # Page-level axis ticks often sit on a different line than the
                # phenomenon caption; merge so blocks on the page can align.
                facets = merge_facets(extract_condition_facets(block), page_facets)
                content = block
                prose = prose_for_facets(facets)
                if prose and prose not in content:
                    content = f"{content}\n{prose}"
                elif page_prose and page_prose not in content and facets.ranges:
                    content = f"{content}\n{page_prose}"
                metadata: dict[str, object] = {}
                if not facets.is_empty:
                    metadata["condition_facets"] = facets.to_metadata()
                if element_type is ElementType.TABLE:
                    metadata["caption"] = f"Page {page_number} table"
                if element_type is ElementType.EQUATION:
                    metadata["latex"] = block
                    metadata["semantic_description"] = block
                if element_type is ElementType.HEADING:
                    metadata["level"] = 2
                elements.append(
                    RawElement(
                        element_type=element_type,
                        page_start=page_number,
                        page_end=page_number,
                        reading_order=order,
                        section_path=[f"Page {page_number}"],
                        raw_content=block,
                        normalized_content=content,
                        metadata=metadata,
                    )
                )
                order += 1
    finally:
        document.close()

    warnings: list[str] = []
    if page_count > limit:
        warnings.append(f"truncated_to_{limit}_of_{page_count}_pages")
    if not elements and not pages:
        raise ValidationError(
            "No extractable text found in PDF (may be scanned-only)",
            details={"filename": filename},
        )
    return RawParserResult(
        parser_name="pdfium",
        parser_version="pdfium-extractor-1",
        title=filename,
        page_count=len(pages),
        pages=pages,
        elements=elements,
        warnings=warnings,
        metadata={"page_texts": {str(k): v[:2000] for k, v in page_texts.items()}},
    )


def extract_text_raw(data: bytes, *, filename: str) -> RawParserResult:
    """Extract plain text / markdown documents."""
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValidationError("Empty text document", details={"filename": filename})
    blocks = split_page_blocks(text) or [text]
    elements = [
        RawElement(
            element_type=ElementType.TEXT,
            page_start=1,
            page_end=1,
            reading_order=index,
            raw_content=block,
            normalized_content=block,
        )
        for index, block in enumerate(blocks)
    ]
    return RawParserResult(
        parser_name="plaintext",
        parser_version="local-1",
        title=filename,
        page_count=1,
        pages=[RawPage(page_number=1, text_density=float(len(text)))],
        elements=elements,
        warnings=[],
    )
