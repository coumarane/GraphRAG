"""MinerU / Marker payload mapper tests (no heavy SDK required)."""

from __future__ import annotations

from enterprise_rag.application.ingestion.local_pipeline import _stamp_hybrid_vision_provenance
from enterprise_rag.application.ingestion.parsing_audit_collector import ParsingAuditCollector
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.parsing.audit import ElementProcessingStatus
from enterprise_rag.infrastructure.parsers.marker.convert import (
    marker_blocks_to_payload,
    marker_markdown_to_payload,
)
from enterprise_rag.infrastructure.parsers.mineru.convert import (
    content_list_to_payload,
    markdown_to_payload,
)
from enterprise_rag.infrastructure.parsers.convert import dict_to_raw_result


def test_mineru_content_list_maps_images_and_pages() -> None:
    payload = content_list_to_payload(
        [
            {"type": "title", "text": "Intro", "page_idx": 0},
            {"type": "image", "img_path": "figs/a.png", "page_idx": 0},
            {"type": "table", "table_body": "|a|b|", "page_idx": 1},
            {"type": "equation", "latex": "E=mc^2", "page_idx": 1},
        ],
        filename="demo.pdf",
    )
    raw = dict_to_raw_result("mineru", payload)
    assert raw.parser_name == "mineru"
    assert raw.page_count >= 2
    types = {el.element_type.value for el in raw.elements}
    assert "heading" in types
    assert "image" in types
    assert "table" in types
    assert "equation" in types
    image_page = next(el for el in raw.elements if el.element_type.value == "image")
    assert image_page.page_start == 1


def test_marker_blocks_map_nested_structure() -> None:
    payload = marker_blocks_to_payload(
        {
            "block_type": "Document",
            "children": [
                {
                    "block_type": "SectionHeader",
                    "html": "Results",
                    "page": 2,
                    "children": [],
                },
                {
                    "block_type": "Picture",
                    "page": 2,
                    "html": "",
                    "children": [],
                },
                {
                    "block_type": "Table",
                    "page": 3,
                    "html": "<table></table>",
                    "children": [],
                },
            ],
        },
        filename="slide.pdf",
    )
    raw = dict_to_raw_result("marker", payload)
    types = [el.element_type.value for el in raw.elements]
    assert "heading" in types
    assert "image" in types
    assert "table" in types


def test_markdown_fallbacks_produce_elements() -> None:
    mineru = markdown_to_payload("# Title\n\nBody", filename="a.pdf")
    marker = marker_markdown_to_payload("# Title\n\nBody", filename="b.pdf")
    assert mineru["elements"]
    assert marker["elements"]
    assert "mineru_page_provenance_unavailable" in mineru["warnings"]
    assert "marker_page_provenance_unavailable" in marker["warnings"]


def test_hybrid_stamp_works_for_layout_parsers() -> None:
    for parser in ("mineru", "marker", "paddleocr", "pdfium", "docling"):
        audit = ParsingAuditCollector(
            tenant_id=new_id(),
            document_id=new_id(),
            version_id=new_id(),
            ingestion_run_id=new_id(),
        )
        report = audit.element_detected(
            page_number=2,
            normalized_element_type="image",
            detector=parser,
            parser_name=parser,
            status=ElementProcessingStatus.DETECTED,
        )
        _stamp_hybrid_vision_provenance(
            audit,
            enriched_pages=[2],
            vision_model="gpt-4o-mini",
            layout_parser=parser,
        )
        updated = next(
            item
            for item in audit._elements
            if item.element_report_id == report.element_report_id
        )
        assert updated.detector == f"{parser}+vision"
        assert updated.model_name == "gpt-4o-mini"
        assert updated.processing_tool == "parser+vision"
