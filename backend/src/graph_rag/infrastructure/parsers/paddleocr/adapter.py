"""PaddleOCR parser adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from graph_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParseSource,
    RawParserResult,
)
from graph_rag.infrastructure.parsers.base import (
    DEFAULT_PARSE_TIMEOUT_SECONDS,
    require_optional_dependency,
    run_parser_sync,
)
from graph_rag.infrastructure.parsers.convert import dict_to_raw_result
from graph_rag.infrastructure.parsers.paddleocr.convert import paddleocr_convert
from graph_rag.infrastructure.parsers.pdfium.inspector import PdfiumInspector

PaddleOCRConvertFn = Callable[[bytes, str, ParseOptions], dict[str, Any]]


class PaddleOCRParser:
    """PaddleOCR adapter for scanned PDFs and images.

    After OCR layout/text extraction, the local ingest pipeline can still run
    hybrid GPT vision enrichment on image-heavy pages (``paddleocr+vision``).
    """

    name = ParserName.PADDLEOCR.value

    def __init__(
        self,
        inspector: PdfiumInspector | None = None,
        convert_fn: PaddleOCRConvertFn | None = None,
    ) -> None:
        self._inspector = inspector or PdfiumInspector()
        self._convert_fn = convert_fn or paddleocr_convert
        self._uses_default_convert = convert_fn is None

    async def inspect(self, source: ParseSource) -> ParserInspection:
        return await self._inspector.inspect(source)

    async def parse(self, source: ParseSource, options: ParseOptions) -> RawParserResult:
        if self._uses_default_convert:
            require_optional_dependency("paddleocr", extra_name="parsers-ocr")
        data = source.require_bytes()
        payload = await run_parser_sync(
            lambda: self._convert_fn(data, source.filename, options),
            timeout_seconds=DEFAULT_PARSE_TIMEOUT_SECONDS,
        )
        return dict_to_raw_result(self.name, payload)
