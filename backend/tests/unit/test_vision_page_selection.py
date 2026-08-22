"""Vision page selection prefers sparse image/map slides over empty later pages."""

from __future__ import annotations

from graph_rag.application.ingestion.local_pipeline import _select_vision_pages
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.parsing.types import RawElement, RawPage, RawParserResult


def _page(n: int, *, density: float | None = None, coverage: float | None = None) -> RawPage:
    return RawPage(page_number=n, text_density=density, image_coverage=coverage)


def _el(
    page: int,
    text: str,
    *,
    element_type: ElementType = ElementType.TEXT,
    order: int = 0,
) -> RawElement:
    return RawElement(
        element_type=element_type,
        page_start=page,
        page_end=page,
        reading_order=order,
        raw_content=text or None,
        normalized_content=text or None,
    )


def test_select_vision_prefers_early_map_slide_over_empty_tail_pages() -> None:
    pages = [_page(n) for n in range(1, 116)]
    elements = [
        _el(1, "Cover title", order=0),
        _el(4, "Created in 1947\nHead office: Osaka\nOther sections: food additives", order=1),
        _el(4, "", element_type=ElementType.IMAGE, order=2),
        _el(10, "Product catalog text " * 40, order=3),
    ]
    raw = RawParserResult(
        parser_name="docling",
        page_count=115,
        pages=pages,
        elements=elements,
    )
    selected = _select_vision_pages(raw, max_pages=28)
    assert 4 in selected
    # Equal-score empty pages must not crowd out the map slide via reverse page order.
    assert selected.index(4) < len(selected)


def test_select_vision_forces_image_sparse_pages() -> None:
    raw = RawParserResult(
        parser_name="docling",
        page_count=5,
        pages=[_page(n) for n in range(1, 6)],
        elements=[
            _el(2, "Short caption", order=0),
            _el(2, "", element_type=ElementType.IMAGE, order=1),
            _el(5, "Dense paragraph " * 80, order=2),
        ],
    )
    selected = _select_vision_pages(raw, max_pages=2)
    assert 2 in selected


def test_select_vision_prioritizes_all_docling_image_pages() -> None:
    """Pages where Docling found IMAGE elements consume vision budget first."""
    elements = [
        _el(1, "Cover", order=0),
        _el(3, "", element_type=ElementType.IMAGE, order=1),
        _el(7, "caption", order=2),
        _el(7, "", element_type=ElementType.IMAGE, order=3),
        _el(10, "Dense text " * 100, order=4),
    ]
    raw = RawParserResult(
        parser_name="docling",
        page_count=12,
        pages=[_page(n) for n in range(1, 13)],
        elements=elements,
    )
    selected = _select_vision_pages(raw, max_pages=2)
    assert selected == [3, 7]


def test_select_vision_tie_break_prefers_earlier_page() -> None:
    raw = RawParserResult(
        parser_name="docling",
        page_count=3,
        pages=[_page(1, density=0.0), _page(2, density=0.0), _page(3, density=0.0)],
        elements=[],
    )
    selected = _select_vision_pages(raw, max_pages=1)
    assert selected == [1]


def test_select_vision_forces_flat_chart_ocr_without_image_element() -> None:
    """BNB-style patch-test charts: PaddleOCR emits text/% only, no IMAGE element."""
    chart_bits = [
        "Test Report : BPDO-800N (1,3-Propanediol)",
        "Table 1. No Skin Irritation.",
        "Human Skin Patch Test Results",
        "Irritation Response, %",
        "30%",
        "21.7%",
        "22.7%",
        "20%",
        "10%",
        "8.2%",
        "0%",
        "25%",
        "50%",
        "75%",
        "Concentration Level",
        "BPDO-800N",
        "Propylene Glycol",
        "Control",
        "No visible irritation reaction is found with 75% 1.3-Propanediol",
    ]
    elements = [
        _el(11, text, order=i) for i, text in enumerate(chart_bits)
    ] + [
        _el(12, "Short caption", order=100),
        _el(12, "", element_type=ElementType.IMAGE, order=101),
        _el(5, "Dense product description " * 40, order=102),
    ]
    raw = RawParserResult(
        parser_name="paddleocr",
        page_count=15,
        pages=[_page(n) for n in range(1, 16)],
        elements=elements,
    )
    selected = _select_vision_pages(raw, max_pages=2)
    assert 11 in selected


def test_select_vision_max_pages_zero_disables() -> None:
    raw = RawParserResult(
        parser_name="paddleocr",
        page_count=3,
        pages=[_page(n) for n in range(1, 4)],
        elements=[_el(1, "30% 21.7% patch test irritation concentration", order=0)],
    )
    assert _select_vision_pages(raw, max_pages=0) == []


def test_select_vision_prioritizes_flat_chart_when_budget_is_one() -> None:
    elements = [
        _el(3, "Short caption", order=0),
        _el(3, "", element_type=ElementType.IMAGE, order=1),
        _el(
            11,
            "Human Skin Patch Test Results Irritation Response, % "
            "30% 21.7% 22.7% 20% 10% 8.2% 0% 25% 50% 75% Concentration Level "
            "BPDO-800N Propylene Glycol Control",
            order=2,
        ),
    ]
    raw = RawParserResult(
        parser_name="paddleocr",
        page_count=15,
        pages=[_page(n) for n in range(1, 16)],
        elements=elements,
    )
    assert _select_vision_pages(raw, max_pages=1) == [11]
