"""PaddleOCR / PDFium image markers for hybrid vision parity."""

from __future__ import annotations

from graph_rag.domain.elements.enums import ElementType
from graph_rag.infrastructure.parsers.convert import dict_to_raw_result
from graph_rag.infrastructure.parsers.pdfium.extractor import extract_pdf_raw


def _blankish_pdf_bytes() -> bytes:
    """Minimal one-page PDF with almost no extractable text (sparse page)."""
    # Tiny valid PDF: empty content stream → pdfium text_density ~0, IMAGE marker.
    return b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>endobj
4 0 obj<</Length 0>>stream
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000052 00000 n 
0000000101 00000 n 
0000000178 00000 n 
trailer<</Size 5/Root 1 0 R>>
startxref
227
%%EOF
"""


def test_pdfium_sparse_page_emits_image_marker() -> None:
    raw = extract_pdf_raw(_blankish_pdf_bytes(), filename="blank.pdf", max_pages=1)
    assert raw.page_count == 1
    assert raw.pages[0].image_coverage >= 0.5
    assert any(el.element_type is ElementType.IMAGE for el in raw.elements)


def test_paddleocr_payload_includes_page_image_marker() -> None:
    """Simulate convert output shape after OCR (image marker per page)."""
    payload = {
        "page_count": 1,
        "pages": [
            {
                "page_number": 1,
                "text_density": 20.0,
                "image_coverage": 0.95,
                "is_scanned": True,
            }
        ],
        "elements": [
            {
                "type": "text",
                "page": 1,
                "reading_order": 0,
                "text": "OCR LINE",
                "ocr_confidence": 0.9,
            },
            {
                "type": "image",
                "page": 1,
                "reading_order": 1,
                "text": "",
                "metadata": {"source": "paddleocr_page_image"},
            },
        ],
        "warnings": [],
        "metadata": {},
    }
    raw = dict_to_raw_result("paddleocr", payload)
    assert any(el.element_type is ElementType.IMAGE for el in raw.elements)
