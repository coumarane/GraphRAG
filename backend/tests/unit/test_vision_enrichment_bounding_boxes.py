"""Vision-enriched elements (chart/image/table/formula) must carry a bounding box.

Regression test for a bug where ``_vision_enrich_pages`` built ``RawElement``s
from LLM vision output without ever setting ``bounding_boxes``, even though
the crop/page region (``target.bbox``) used to render the image sent to the
model was right there. Every element downstream of vision enrichment
(chart descriptions, table transcriptions, etc.) therefore had no geometry
-- the "Parsed content" page viewer's click-to-highlight overlay silently
skipped these elements, which are exactly the interesting ones (charts,
figures) users click on.
"""

from __future__ import annotations

import json

import pytest

from graph_rag.application.ingestion.local_pipeline import _vision_enrich_pages
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.parsing.types import RawElement, RawPage, RawParserResult
from graph_rag.infrastructure.models.fake import FakeChatModel

_VISION_PAYLOAD = {
    "ocr_text": "",
    "page_summary": "",
    "measurement_conditions": "",
    "callouts": [],
    "figures": [
        {
            "type": "chart",
            "title": "Viscosity vs temperature",
            "description": "Viscosity declines as temperature rises.",
            "values_markdown": "| Temp | Viscosity |\n|---|---|\n| 20 | 12 |",
            "ocr_labels": "",
            "series_ranking": "",
        }
    ],
    "tables": [],
    "formulas": [],
}


def _raw_with_one_image_on_page(page: int) -> RawParserResult:
    return RawParserResult(
        parser_name="docling",
        page_count=page,
        pages=[RawPage(page_number=n) for n in range(1, page + 1)],
        elements=[
            RawElement(
                element_type=ElementType.IMAGE,
                page_start=page,
                page_end=page,
                reading_order=0,
                raw_content=None,
                normalized_content=None,
            )
        ],
    )


@pytest.mark.asyncio
async def test_vision_enriched_chart_element_carries_bounding_box(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "graph_rag.application.ingestion.local_pipeline.render_visual_png",
        lambda *args, **kwargs: b"\x89PNG\r\n\x1a\nfake",
    )
    chat = FakeChatModel(response_fn=lambda _req: json.dumps(_VISION_PAYLOAD))

    raw = _raw_with_one_image_on_page(3)
    extras, enriched_pages, _target_count, failed = await _vision_enrich_pages(
        chat, b"%PDF-1.4\nplaceholder\n%%EOF\n", raw
    )

    assert failed == 0
    assert 3 in enriched_pages
    chart_elements = [el for el in extras if el.element_type == ElementType.CHART]
    assert len(chart_elements) == 1
    chart = chart_elements[0]
    assert len(chart.bounding_boxes) == 1
    bbox = chart.bounding_boxes[0]
    assert bbox.page_number == 3
    # No target.bbox on this fixture (a full-page IMAGE element with no
    # geometry of its own) -- falls back to the whole page.
    assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == (0.0, 0.0, 1.0, 1.0)


@pytest.mark.asyncio
async def test_vision_enrichment_no_targets_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat = FakeChatModel(text="{}")
    raw = RawParserResult(parser_name="docling", page_count=1, pages=[RawPage(page_number=1)])
    extras, enriched_pages, target_count, failed = await _vision_enrich_pages(
        chat, b"%PDF-1.4\nplaceholder\n%%EOF\n", raw
    )
    assert extras == []
    assert enriched_pages == []
    assert target_count == 0
    assert failed == 0
