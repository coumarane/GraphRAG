"""Parser registry and fallback orchestration."""

from __future__ import annotations

from enterprise_rag.domain.documents.document import NormalizedDocument
from enterprise_rag.domain.parsing.normalize import normalize_parser_result
from enterprise_rag.domain.parsing.protocols import MultimodalDocumentParser
from enterprise_rag.domain.parsing.routing import AutomaticParserRouter
from enterprise_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParserSelection,
    ParseSource,
    RawParserResult,
)
from enterprise_rag.infrastructure.parsers.docling import DoclingParser
from enterprise_rag.infrastructure.parsers.marker import MarkerParser
from enterprise_rag.infrastructure.parsers.mineru import MinerUParser
from enterprise_rag.infrastructure.parsers.paddleocr import PaddleOCRParser
from enterprise_rag.infrastructure.parsers.pdfium import PdfiumInspector, PdfiumParser
from enterprise_rag.infrastructure.parsers.text import TextDocumentParser
from enterprise_rag.shared.exceptions import ParserError
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)


class ParserRegistry:
    """Named multimodal parser registry."""

    def __init__(
        self,
        parsers: dict[str, MultimodalDocumentParser] | None = None,
        inspector: PdfiumInspector | None = None,
    ) -> None:
        inspector = inspector or PdfiumInspector()
        self._inspector = inspector
        self._parsers: dict[str, MultimodalDocumentParser] = parsers or {
            ParserName.DOCLING.value: DoclingParser(inspector=inspector),
            ParserName.MINERU.value: MinerUParser(inspector=inspector),
            ParserName.MARKER.value: MarkerParser(inspector=inspector),
            ParserName.PADDLEOCR.value: PaddleOCRParser(inspector=inspector),
            ParserName.PDFIUM.value: PdfiumParser(inspector=inspector),
            ParserName.TEXT.value: TextDocumentParser(inspector=inspector),
        }

    def get(self, name: ParserName | str) -> MultimodalDocumentParser:
        key = name.value if isinstance(name, ParserName) else name
        try:
            return self._parsers[key]
        except KeyError as exc:
            raise ParserError(
                "Parser is not registered",
                details={"parser": key, "available": sorted(self._parsers)},
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._parsers)


class ParseDocumentService:
    """Inspect, route, parse with fallbacks, and normalize."""

    def __init__(
        self,
        registry: ParserRegistry | None = None,
        router: AutomaticParserRouter | None = None,
    ) -> None:
        self._registry = registry or ParserRegistry()
        self._router = router or AutomaticParserRouter()

    async def inspect(self, source: ParseSource) -> ParserInspection:
        # Prefer a registered parser's inspector; fall back to PDFium.
        try:
            inspector_parser = self._registry.get(ParserName.DOCLING)
        except ParserError:
            return await PdfiumInspector().inspect(source)
        return await inspector_parser.inspect(source)

    async def select_parser(
        self,
        source: ParseSource,
        options: ParseOptions | None = None,
    ) -> ParserSelection:
        inspection = await self.inspect(source)
        return self._router.select(
            inspection=inspection,
            options=options,
            filename=source.filename,
        )

    async def parse(
        self,
        source: ParseSource,
        options: ParseOptions | None = None,
    ) -> tuple[NormalizedDocument, ParserSelection, list[str]]:
        opts = options or ParseOptions()
        selection = await self.select_parser(source, opts)
        attempted: list[str] = []
        warnings: list[str] = []
        chain = [selection.primary, *selection.fallbacks]
        last_error: Exception | None = None

        for parser_name in chain:
            parser = self._registry.get(parser_name)
            attempted.append(parser_name.value)
            try:
                raw = await parser.parse(source, opts)
                document = normalize_parser_result(raw, source)
                document.parser_info.attempted_parsers = attempted
                document.parser_info.warnings = list(raw.warnings) + warnings
                document.parser_info.profile = selection.profile.value
                return document, selection, attempted
            except Exception as exc:
                last_error = exc
                message = f"{parser_name.value} failed: {exc}"
                warnings.append(message)
                logger.warning(
                    "parser_attempt_failed",
                    parser=parser_name.value,
                    error=str(exc),
                )
                if opts.failure_mode == "fail_fast":
                    break

        raise ParserError(
            "All parser attempts failed",
            details={
                "attempted": attempted,
                "failure_mode": opts.failure_mode,
                "last_error": str(last_error) if last_error else None,
            },
            cause=last_error,
        )

    async def parse_raw(
        self,
        source: ParseSource,
        parser_name: ParserName,
        options: ParseOptions | None = None,
    ) -> RawParserResult:
        parser = self._registry.get(parser_name)
        return await parser.parse(source, options or ParseOptions())
