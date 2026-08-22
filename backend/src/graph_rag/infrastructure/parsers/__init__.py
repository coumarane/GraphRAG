"""Parser infrastructure adapters."""

from graph_rag.infrastructure.parsers.docling import DoclingParser
from graph_rag.infrastructure.parsers.marker import MarkerParser
from graph_rag.infrastructure.parsers.mineru import MinerUParser
from graph_rag.infrastructure.parsers.paddleocr import PaddleOCRParser
from graph_rag.infrastructure.parsers.pdfium import PdfiumInspector
from graph_rag.infrastructure.parsers.registry import ParseDocumentService, ParserRegistry
from graph_rag.infrastructure.parsers.text import TextDocumentParser

__all__ = [
    "DoclingParser",
    "MarkerParser",
    "MinerUParser",
    "PaddleOCRParser",
    "ParseDocumentService",
    "ParserRegistry",
    "PdfiumInspector",
    "TextDocumentParser",
]
