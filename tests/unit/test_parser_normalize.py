"""Parser normalization and adapter contract tests."""

from __future__ import annotations

import pytest

from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.parsing.normalize import empty_parse_source, normalize_parser_result
from enterprise_rag.domain.parsing.types import (
    ParseOptions,
    ParserName,
    RawElement,
    RawPage,
    RawParserResult,
)
from enterprise_rag.infrastructure.parsers.convert import dict_to_raw_result
from enterprise_rag.infrastructure.parsers.docling import DoclingParser
from enterprise_rag.infrastructure.parsers.marker import MarkerParser
from enterprise_rag.infrastructure.parsers.mineru import MinerUParser
from enterprise_rag.infrastructure.parsers.paddleocr import PaddleOCRParser
from enterprise_rag.infrastructure.parsers.registry import ParseDocumentService, ParserRegistry
from enterprise_rag.infrastructure.parsers.text import TextDocumentParser
from enterprise_rag.shared.exceptions import ParserError
from tests.unit.contract_support import assert_matches_contract


def _sample_payload() -> dict[str, object]:
    return {
        "parser_version": "test-1",
        "title": "Sample Doc",
        "language": "en",
        "page_count": 2,
        "pages": [
            {"page_number": 1, "width": 612.0, "height": 792.0},
            {"page_number": 2, "width": 612.0, "height": 792.0},
        ],
        "elements": [
            {
                "type": "heading",
                "text": "Introduction",
                "page": 1,
                "reading_order": 0,
                "level": 1,
                "section_path": ["Introduction"],
            },
            {
                "type": "text",
                "text": "Body paragraph.",
                "page": 1,
                "reading_order": 1,
                "section_path": ["Introduction"],
            },
            {
                "type": "table",
                "text": "| a | b |\n| 1 | 2 |",
                "page": 2,
                "reading_order": 0,
                "section_path": ["Results"],
                "metadata": {"caption": "Metrics"},
            },
            {
                "type": "equation",
                "text": "E=mc^2",
                "page": 2,
                "reading_order": 1,
                "latex": "E=mc^2",
                "section_path": ["Results"],
            },
            {
                "type": "image",
                "text": "",
                "page": 2,
                "reading_order": 2,
                "metadata": {"visual_description": "Chart thumbnail"},
                "section_path": ["Results"],
            },
        ],
        "warnings": [],
    }


def test_dict_to_raw_and_normalize_matches_contract() -> None:
    raw = dict_to_raw_result("docling", _sample_payload())
    source = empty_parse_source(
        filename="sample.pdf",
        mime_type="application/pdf",
        content=b"%PDF-1.4",
    )
    document = normalize_parser_result(raw, source)
    assert document.page_count == 2
    assert len(document.elements) == 5
    assert document.elements[0].element_type is ElementType.HEADING
    assert document.elements[0].next_element_id == document.elements[1].element_id
    assert document.elements[1].previous_element_id == document.elements[0].element_id
    assert any(section.title == "Introduction" for section in document.sections)
    assert_matches_contract("normalized-document", document.model_dump(mode="json"))


def test_normalize_rejects_invalid_page_range() -> None:
    source = empty_parse_source(filename="bad.pdf", mime_type="application/pdf")
    raw = RawParserResult(
        parser_name="docling",
        page_count=1,
        pages=[RawPage(page_number=1)],
        elements=[
            RawElement(
                element_type=ElementType.TEXT,
                page_start=2,
                page_end=1,
                reading_order=0,
                raw_content="x",
            )
        ],
    )
    with pytest.raises(ParserError, match="page range"):
        normalize_parser_result(raw, source)


@pytest.mark.asyncio
async def test_text_parser_markdown() -> None:
    parser = TextDocumentParser()
    source = empty_parse_source(
        filename="notes.md",
        mime_type="text/markdown",
        content=b"# Title\n\nHello world.\n",
    )
    raw = await parser.parse(source, ParseOptions())
    document = normalize_parser_result(raw, source)
    assert document.parser_info.parser_name == "text"
    assert document.elements[0].element_type is ElementType.HEADING
    assert_matches_contract("normalized-document", document.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_docling_adapter_with_injected_convert() -> None:
    parser = DoclingParser(convert_fn=lambda _data, _name: _sample_payload())
    source = empty_parse_source(
        filename="enterprise.pdf",
        mime_type="application/pdf",
        content=b"%PDF",
    )
    raw = await parser.parse(source, ParseOptions())
    document = normalize_parser_result(raw, source)
    assert document.parser_info.parser_name == ParserName.DOCLING.value
    assert_matches_contract("normalized-document", document.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_mineru_marker_paddle_adapters_with_injected_convert() -> None:
    payload = _sample_payload()
    source = empty_parse_source(filename="paper.pdf", mime_type="application/pdf", content=b"%PDF")
    adapters = [
        MinerUParser(convert_fn=lambda _d, _n: payload),
        MarkerParser(convert_fn=lambda _d, _n: payload),
        PaddleOCRParser(convert_fn=lambda _d, _n, _o: payload),
    ]
    for adapter in adapters:
        raw = await adapter.parse(source, ParseOptions())
        document = normalize_parser_result(raw, source)
        assert document.parser_info.parser_name == adapter.name
        assert_matches_contract("normalized-document", document.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_parse_service_fallback_chain() -> None:
    def fail(_data: bytes, _name: str) -> dict[str, object]:
        raise RuntimeError("primary failed")

    registry = ParserRegistry(
        parsers={
            ParserName.DOCLING.value: DoclingParser(convert_fn=fail),
            ParserName.MARKER.value: MarkerParser(convert_fn=lambda _d, _n: _sample_payload()),
            ParserName.TEXT.value: TextDocumentParser(),
        }
    )
    service = ParseDocumentService(registry=registry)
    source = empty_parse_source(
        filename="memo.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"PK",
    )
    document, selection, attempted = await service.parse(
        source,
        ParseOptions(parser_override=ParserName.DOCLING, fallback_parsers=[ParserName.MARKER]),
    )
    assert selection.primary is ParserName.DOCLING
    assert attempted == ["docling", "marker"]
    assert document.parser_info.parser_name == "marker"
    assert document.parser_info.attempted_parsers == attempted
    assert_matches_contract("normalized-document", document.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_parse_service_fail_fast() -> None:
    def fail(_data: bytes, _name: str) -> dict[str, object]:
        raise RuntimeError("boom")

    registry = ParserRegistry(
        parsers={
            ParserName.DOCLING.value: DoclingParser(convert_fn=fail),
            ParserName.MARKER.value: MarkerParser(convert_fn=lambda _d, _n: _sample_payload()),
        }
    )
    service = ParseDocumentService(registry=registry)
    source = empty_parse_source(
        filename="a.txt",
        mime_type="text/plain",
        content=b"hello",
    )
    with pytest.raises(ParserError, match="All parser attempts failed"):
        await service.parse(
            source,
            ParseOptions(
                parser_override=ParserName.DOCLING,
                fallback_parsers=[ParserName.MARKER],
                failure_mode="fail_fast",
            ),
        )
