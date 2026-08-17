"""Visual-region routing for charts, SEM, photos, and scans."""

from __future__ import annotations

from enterprise_rag.application.ingestion.visual_enrichment import (
    classify_visual_kind,
    collect_visual_targets,
    recommended_tool,
)
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.parsing.types import RawElement, RawPage, RawParserResult


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


def test_classify_sem_from_caption() -> None:
    element = _el(2, "", element_type=ElementType.IMAGE, order=1)
    kind = classify_visual_kind(
        element=element,
        context="Figure 2. SEM micrograph of surface-treated mica, 5 µm scale bar",
    )
    assert kind == "sem"
    assert recommended_tool(kind) == "vision"


def test_classify_chart_from_element_type() -> None:
    element = _el(3, "Irritation response", element_type=ElementType.CHART, order=0)
    assert classify_visual_kind(element=element, context="") == "chart"


def test_collect_every_image_and_flat_chart_page() -> None:
    raw = RawParserResult(
        parser_name="docling",
        page_count=4,
        pages=[
            RawPage(page_number=1, text_density=800, image_coverage=0.0),
            RawPage(page_number=2, text_density=40, image_coverage=0.8),
            RawPage(page_number=3, text_density=120, image_coverage=0.1, is_scanned=True),
            RawPage(page_number=4, text_density=50, image_coverage=0.0),
        ],
        elements=[
            _el(1, "Cover title", order=0),
            _el(2, "SEM image of particles", order=1),
            _el(2, "", element_type=ElementType.IMAGE, order=2),
            _el(
                4,
                "Human Skin Patch Test Results Irritation Response, % "
                "30% 21.7% 22.7% 20% 10% 8.2% 0% 25% 50% 75% Concentration Level",
                order=3,
            ),
        ],
    )
    targets = collect_visual_targets(raw)
    kinds = {(item.page_number, item.kind) for item in targets}
    assert (2, "sem") in kinds
    assert any(item.page_number == 4 and item.kind == "chart" for item in targets)
    assert any(item.page_number == 3 and item.kind == "scan" for item in targets)
    assert all(item.tool == "vision" for item in targets)
