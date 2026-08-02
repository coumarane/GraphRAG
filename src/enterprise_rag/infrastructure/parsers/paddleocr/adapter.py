"""PaddleOCR parser adapter."""

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

PaddleOCRConvertFn = Callable[[bytes, str, ParseOptions], dict[str, Any]]


def _default_paddleocr_convert(data: bytes, filename: str, options: ParseOptions) -> dict[str, Any]:
    require_optional_dependency("paddleocr")
    raise NotImplementedError(
        "PaddleOCR SDK conversion requires a pinned paddleocr integration; "
        "inject convert_fn for runtime use"
    )


class PaddleOCRParser:
    """PaddleOCR adapter for scanned PDFs and images."""

    name = ParserName.PADDLEOCR.value

    def __init__(
        self,
        inspector: PdfiumInspector | None = None,
        convert_fn: PaddleOCRConvertFn | None = None,
    ) -> None:
        self._inspector = inspector or PdfiumInspector()
        self._convert_fn = convert_fn or _default_paddleocr_convert

    async def inspect(self, source: ParseSource) -> ParserInspection:
        return await self._inspector.inspect(source)

    async def parse(self, source: ParseSource, options: ParseOptions) -> RawParserResult:
        data = source.require_bytes()
        payload = await run_parser_sync(
            lambda: self._convert_fn(data, source.filename, options)
        )
        return dict_to_raw_result(self.name, payload)
