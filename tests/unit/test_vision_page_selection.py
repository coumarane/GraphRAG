"""Vision page selection prefers sparse image/map slides over empty later pages."""

from __future__ import annotations

from enterprise_rag.application.ingestion.local_pipeline import _select_vision_pages
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.parsing.types import RawElement, RawPage, RawParserResult


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


def test_select_vision_tie_break_prefers_earlier_page() -> None:
    raw = RawParserResult(
        parser_name="docling",
        page_count=3,
        pages=[_page(1, density=0.0), _page(2, density=0.0), _page(3, density=0.0)],
        elements=[],
    )
    selected = _select_vision_pages(raw, max_pages=1)
    assert selected == [1]
