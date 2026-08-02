"""Multimodal context builder and enrichment processor tests."""

from __future__ import annotations

import pytest

from enterprise_rag.application.multimodal import EnrichDocumentService
from enterprise_rag.config.settings import MultimodalSettings
from enterprise_rag.domain.documents import NormalizedDocument, ParserInfo
from enterprise_rag.domain.elements import (
    CaptionElement,
    ChartElement,
    EquationElement,
    HeadingElement,
    ImageElement,
    PageHeaderElement,
    TableData,
    TableElement,
    TextElement,
)
from enterprise_rag.domain.ids import content_sha256_hex, new_id
from enterprise_rag.domain.multimodal import ContextBuilderConfig, ElementContextBuilder
from enterprise_rag.infrastructure.models import FakeStructuredExtractor, FakeTokenCounter


def _hash(text: str) -> str:
    return content_sha256_hex(text)


def _doc_with_elements() -> NormalizedDocument:
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    ids = {
        "tenant_id": tenant_id,
        "document_id": document_id,
        "version_id": version_id,
    }
    header = PageHeaderElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=0,
        content_hash=_hash("header"),
        normalized_content="CONFIDENTIAL",
    )
    heading = HeadingElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=1,
        section_path=["Methods"],
        content_hash=_hash("Methods"),
        level=1,
        normalized_content="Methods",
    )
    before = TextElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=2,
        section_path=["Methods"],
        content_hash=_hash("before"),
        normalized_content="The apparatus is shown below.",
        raw_content="The apparatus is shown below.",
    )
    image = ImageElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=3,
        section_path=["Methods"],
        content_hash=_hash("image"),
        raw_content="[image]",
        normalized_content=None,
    )
    caption = CaptionElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=4,
        section_path=["Methods"],
        content_hash=_hash("caption"),
        normalized_content="Figure 1. Process flow",
        target_element_id=image.element_id,
    )
    after = TextElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=5,
        section_path=["Methods"],
        content_hash=_hash("after"),
        normalized_content="Flow continues to the reactor.",
    )
    table = TableElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=6,
        section_path=["Methods"],
        content_hash=_hash("table"),
        raw_content="| Temp | Viscosity |",
        table=TableData(
            caption="Table 1",
            markdown="| Temp | Viscosity |\n| 20 | 12 |",
            column_headers=["Temp", "Viscosity"],
        ),
    )
    chart = ChartElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=7,
        section_path=["Methods"],
        content_hash=_hash("chart"),
        raw_content="[chart]",
    )
    equation = EquationElement(
        element_id=new_id(),
        **ids,
        page_start=1,
        page_end=1,
        reading_order=8,
        section_path=["Methods"],
        content_hash=_hash("eq"),
        latex="E=mc^2",
        raw_content="E=mc^2",
    )
    return NormalizedDocument(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        title="Lab Report",
        source_filename="lab.pdf",
        mime_type="application/pdf",
        page_count=0,
        elements=[header, heading, before, image, caption, after, table, chart, equation],
        parser_info=ParserInfo(parser_name="docling"),
    )


@pytest.mark.asyncio
async def test_context_builder_excludes_headers_and_binds_caption() -> None:
    document = _doc_with_elements()
    image = next(el for el in document.elements if isinstance(el, ImageElement))
    builder = ElementContextBuilder(
        config=ContextBuilderConfig(preceding_elements=3, following_elements=3),
        token_counter=FakeTokenCounter(),
    )
    context = await builder.build(document, image)
    assert context.document_title == "Lab Report"
    assert context.caption == "Figure 1. Process flow"
    assert context.heading == "Methods"
    assert context.preceding_text is not None
    assert "CONFIDENTIAL" not in (context.preceding_text or "")
    assert "apparatus" in (context.preceding_text or "")
    assert context.following_text is not None
    assert "reactor" in (context.following_text or "")


@pytest.mark.asyncio
async def test_context_builder_respects_token_budget() -> None:
    document = _doc_with_elements()
    image = next(el for el in document.elements if isinstance(el, ImageElement))
    builder = ElementContextBuilder(
        config=ContextBuilderConfig(
            preceding_elements=3,
            following_elements=3,
            max_context_tokens=20,
        ),
        token_counter=FakeTokenCounter(),
    )
    context = await builder.build(document, image)
    combined = "\n".join(
        filter(
            None,
            [
                context.preceding_text,
                context.following_text,
                *context.nearby_element_summaries,
                *context.footnotes,
            ],
        )
    )
    assert len(combined) < 200


@pytest.mark.asyncio
async def test_enrich_document_processors_preserve_raw_content() -> None:
    document = _doc_with_elements()
    image = next(el for el in document.elements if isinstance(el, ImageElement))
    table = next(el for el in document.elements if isinstance(el, TableElement))
    equation = next(el for el in document.elements if isinstance(el, EquationElement))
    original_image_raw = image.raw_content
    original_table_cells = list(table.table.cells)
    original_latex = equation.latex

    service = EnrichDocumentService(FakeStructuredExtractor(), token_counter=FakeTokenCounter())
    result = await service.enrich(document)

    enriched_image = next(
        el for el in result.document.elements if el.element_id == image.element_id
    )
    enriched_table = next(
        el for el in result.document.elements if el.element_id == table.element_id
    )
    enriched_chart = next(el for el in result.document.elements if isinstance(el, ChartElement))
    enriched_equation = next(
        el for el in result.document.elements if el.element_id == equation.element_id
    )

    assert isinstance(enriched_image, ImageElement)
    assert enriched_image.raw_content == original_image_raw
    assert enriched_image.visual_description
    assert "Valve" in (enriched_image.ocr_text or "")

    assert isinstance(enriched_table, TableElement)
    assert enriched_table.table.cells == original_table_cells
    assert enriched_table.table.semantic_summary
    assert enriched_table.table.markdown

    assert isinstance(enriched_chart, ChartElement)
    assert enriched_chart.chart_type == "line"
    assert enriched_chart.trends

    assert isinstance(enriched_equation, EquationElement)
    assert enriched_equation.latex == original_latex
    assert enriched_equation.semantic_description
    assert enriched_equation.variables

    assert str(image.element_id) in result.enriched_element_ids
    assert not result.warnings


@pytest.mark.asyncio
async def test_enrich_respects_modality_toggles() -> None:
    document = _doc_with_elements()
    settings = MultimodalSettings(process_images=False, process_charts=True)
    service = EnrichDocumentService(
        FakeStructuredExtractor(),
        settings=settings,
        token_counter=FakeTokenCounter(),
    )
    result = await service.enrich(document)
    image = next(el for el in result.document.elements if isinstance(el, ImageElement))
    chart = next(el for el in result.document.elements if isinstance(el, ChartElement))
    assert image.visual_description is None
    assert chart.chart_type == "line"
    assert str(image.element_id) in result.skipped_element_ids
