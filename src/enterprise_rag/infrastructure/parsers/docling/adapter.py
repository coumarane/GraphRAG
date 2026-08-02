"""Docling parser adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from enterprise_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParseSource,
    RawParserResult,
)
from enterprise_rag.infrastructure.parsers.base import require_optional_dependency, run_parser_sync
from enterprise_rag.infrastructure.parsers.convert import dict_to_raw_result
from enterprise_rag.infrastructure.parsers.pdfium.inspector import PdfiumInspector

DoclingConvertFn = Callable[[bytes, str], dict[str, Any]]


def _default_docling_convert(data: bytes, filename: str) -> dict[str, Any]:
    require_optional_dependency("docling")
    # Lazy import of Docling APIs. Exact API surface varies by version; adapters
    # normalize into a stable intermediate dict for conversion.
    import tempfile
    from pathlib import Path

    from docling.document_converter import DocumentConverter  # type: ignore[import-not-found]

    converter = DocumentConverter()
    suffix = Path(filename).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(data)
        handle.flush()
        result = converter.convert(handle.name)
    document = result.document
    texts: list[dict[str, Any]] = []
    export = getattr(document, "export_to_markdown", None)
    markdown = export() if callable(export) else str(document)
    for index, block in enumerate(part for part in markdown.split("\n\n") if part.strip()):
        texts.append(
            {
                "type": "heading" if block.lstrip().startswith("#") else "text",
                "text": block.lstrip("# ").strip(),
                "page": 1,
                "reading_order": index,
            }
        )
    return {
        "parser_version": getattr(DocumentConverter, "__module__", "docling"),
        "title": filename,
        "page_count": max((item.get("page", 1) for item in texts), default=1),
        "elements": texts,
        "warnings": [],
    }


class DoclingParser:
    """Docling adapter for enterprise PDFs and office documents."""

    name = ParserName.DOCLING.value

    def __init__(
        self,
        inspector: PdfiumInspector | None = None,
        convert_fn: DoclingConvertFn | None = None,
    ) -> None:
        self._inspector = inspector or PdfiumInspector()
        self._convert_fn = convert_fn or _default_docling_convert

    async def inspect(self, source: ParseSource) -> ParserInspection:
        return await self._inspector.inspect(source)

    async def parse(self, source: ParseSource, options: ParseOptions) -> RawParserResult:
        data = source.require_bytes()
        payload = await run_parser_sync(lambda: self._convert_fn(data, source.filename))
        return dict_to_raw_result(self.name, payload)
