"""pypdfium2 parser package."""

from graph_rag.infrastructure.parsers.pdfium.extractor import (
    extract_pdf_raw,
    extract_text_raw,
    split_page_blocks,
)
from graph_rag.infrastructure.parsers.pdfium.inspector import PdfiumInspector
from graph_rag.infrastructure.parsers.pdfium.parser import PdfiumParser

__all__ = [
    "PdfiumInspector",
    "PdfiumParser",
    "extract_pdf_raw",
    "extract_text_raw",
    "split_page_blocks",
]
