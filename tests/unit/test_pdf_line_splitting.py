"""Regression: PDF text extraction must not collapse multi-line pages into one element."""

from __future__ import annotations

from pathlib import Path

from enterprise_rag.infrastructure.parsers.pdfium.extractor import extract_pdf_raw as _extract_pdf_raw


def test_extract_pdf_splits_single_newline_pages() -> None:
    sample = Path("evaluation/corpus/text_heavy.pdf")
    raw = _extract_pdf_raw(sample.read_bytes(), filename=sample.name, max_pages=1)
    assert raw.page_count == 1
    assert len(raw.elements) >= 2


def test_extract_real_tds_produces_multiple_elements() -> None:
    sample = Path("sample_data/Acerola Extract WB-E TDS.pdf")
    if not sample.exists():
        return
    raw = _extract_pdf_raw(sample.read_bytes(), filename=sample.name, max_pages=1)
    assert len(raw.elements) >= 5
