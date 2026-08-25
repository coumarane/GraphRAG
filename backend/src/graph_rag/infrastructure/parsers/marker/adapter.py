"""Marker parser adapter."""

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
from graph_rag.infrastructure.parsers.base import DEFAULT_PARSE_TIMEOUT_SECONDS, run_parser_sync
from graph_rag.infrastructure.parsers.convert import dict_to_raw_result
from graph_rag.infrastructure.parsers.marker.convert import marker_convert
from graph_rag.infrastructure.parsers.pdfium.inspector import PdfiumInspector

MarkerConvertFn = Callable[[bytes, str], dict[str, Any]]


class MarkerParser:
    """Marker adapter used as PDF structured-text fallback.

    After layout extraction, the local ingest pipeline can still run hybrid
    GPT vision enrichment on image-heavy pages (``marker+vision``).
    """

    name = ParserName.MARKER.value

    def __init__(
        self,
        inspector: PdfiumInspector | None = None,
        convert_fn: MarkerConvertFn | None = None,
    ) -> None:
        self._inspector = inspector or PdfiumInspector()
        self._convert_fn = convert_fn or marker_convert

    async def inspect(self, source: ParseSource) -> ParserInspection:
        return await self._inspector.inspect(source)

    async def parse(self, source: ParseSource, options: ParseOptions) -> RawParserResult:
        data = source.require_bytes()
        payload = await run_parser_sync(
            lambda: self._convert_fn(data, source.filename),
            timeout_seconds=DEFAULT_PARSE_TIMEOUT_SECONDS,
        )
        return dict_to_raw_result(self.name, payload)
