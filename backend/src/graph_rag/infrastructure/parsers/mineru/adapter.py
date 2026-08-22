"""MinerU parser adapter."""

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
from graph_rag.infrastructure.parsers.base import run_parser_sync
from graph_rag.infrastructure.parsers.convert import dict_to_raw_result
from graph_rag.infrastructure.parsers.mineru.convert import mineru_convert
from graph_rag.infrastructure.parsers.pdfium.inspector import PdfiumInspector

MinerUConvertFn = Callable[[bytes, str], dict[str, Any]]


class MinerUParser:
    """MinerU adapter for scientific and complex PDFs.

    After layout extraction, the local ingest pipeline can still run hybrid
    GPT vision enrichment on image-heavy pages (``mineru+vision``).
    """

    name = ParserName.MINERU.value

    def __init__(
        self,
        inspector: PdfiumInspector | None = None,
        convert_fn: MinerUConvertFn | None = None,
    ) -> None:
        self._inspector = inspector or PdfiumInspector()
        self._convert_fn = convert_fn or mineru_convert

    async def inspect(self, source: ParseSource) -> ParserInspection:
        return await self._inspector.inspect(source)

    async def parse(self, source: ParseSource, options: ParseOptions) -> RawParserResult:
        data = source.require_bytes()
        payload = await run_parser_sync(lambda: self._convert_fn(data, source.filename))
        return dict_to_raw_result(self.name, payload)
