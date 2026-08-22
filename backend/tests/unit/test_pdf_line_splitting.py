"""Regression: PDF text extraction must not collapse multi-line pages into one element."""

from __future__ import annotations

from pathlib import Path

from graph_rag.domain.retrieval.condition_facets import extract_condition_facets
from graph_rag.infrastructure.parsers.pdfium.extractor import extract_pdf_raw as _extract_pdf_raw


def test_extract_pdf_splits_single_newline_pages() -> None:
    sample = Path("../data/evaluation/corpus/text_heavy.pdf")
    raw = _extract_pdf_raw(sample.read_bytes(), filename=sample.name, max_pages=1)
    assert raw.page_count == 1
    assert len(raw.elements) >= 2


def test_extract_real_tds_produces_multiple_elements() -> None:
    sample = Path("../data/samples/Acerola Extract WB-E TDS.pdf")
    if not sample.exists():
        return
    raw = _extract_pdf_raw(sample.read_bytes(), filename=sample.name, max_pages=1)
    assert len(raw.elements) >= 5


def test_sy_knp_pdfium_emits_condition_facets_for_ph_axis() -> None:
    sample = Path("../data/samples/【Presentation】 SY-KNP.pdf")
    if not sample.exists():
        return
    raw = _extract_pdf_raw(sample.read_bytes(), filename=sample.name, max_pages=13)
    assert raw.page_count >= 10
    page10 = "\n".join(
        (el.normalized_content or el.raw_content or "")
        for el in raw.elements
        if el.page_start == 10
    )
    facets = extract_condition_facets(page10)
    assert "ph" in facets.parameters
    assert facets.ranges
    assert any(el.metadata.get("condition_facets") for el in raw.elements if el.page_start == 10)
