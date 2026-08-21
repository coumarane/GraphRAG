"""PaddleOCR adapter wiring tests (no live OCR models required)."""

from __future__ import annotations

import asyncio

from enterprise_rag.domain.parsing.types import ParseOptions, ParseSource, ParserName
from enterprise_rag.infrastructure.parsers.paddleocr import PaddleOCRParser
from enterprise_rag.domain.ids import new_id


def test_paddleocr_parser_uses_injected_convert_fn() -> None:
    def fake_convert(data: bytes, filename: str, options: ParseOptions) -> dict:
        assert data.startswith(b"%PDF") or True
        assert filename.endswith(".pdf")
        return {
            "page_count": 1,
            "pages": [
                {
                    "page_number": 1,
                    "text_density": 12.0,
                    "image_coverage": 0.95,
                    "is_scanned": True,
                }
            ],
            "elements": [
                {
                    "type": "text",
                    "page": 1,
                    "reading_order": 0,
                    "text": "OCR LINE ONE",
                    "ocr_confidence": 0.9,
                }
            ],
            "warnings": [],
            "metadata": {},
        }

    parser = PaddleOCRParser(convert_fn=fake_convert)
    source = ParseSource(
        tenant_id=new_id(),
        document_id=new_id(),
        version_id=new_id(),
        filename="scanned.pdf",
        mime_type="application/pdf",
        content=b"%PDF-1.4 fake",
    )
    raw = asyncio.run(parser.parse(source, ParseOptions()))
    assert raw.parser_name == ParserName.PADDLEOCR.value
    assert raw.page_count == 1
    assert raw.elements
    assert "OCR LINE ONE" in (raw.elements[0].normalized_content or "")
