"""Parser registry and fallback orchestration."""

from __future__ import annotations

from graph_rag.application.plugins.parsers import (
    build_core_parser_instances,
    build_parser_instances,
    configured_inspector_name,
    resolve_inspector_name,
)
from graph_rag.domain.documents.document import NormalizedDocument
from graph_rag.domain.parsing.normalize import normalize_parser_result
from graph_rag.domain.parsing.protocols import MultimodalDocumentParser
from graph_rag.domain.parsing.routing import AutomaticParserRouter
from graph_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParserSelection,
    ParseSource,
    RawParserResult,
    parser_key,
)
from graph_rag.shared.exceptions import ParserError
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)


class ParserRegistry:
    """Named multimodal parser registry filled from plugin factories."""

    def __init__(
        self,
        parsers: dict[str, MultimodalDocumentParser] | None = None,
        inspector: object | None = None,
        *,
        inspector_name: str | None = None,
    ) -> None:
        del inspector  # retained for call-site compatibility; inspect uses parser slots
        self._parsers: dict[str, MultimodalDocumentParser] = parsers or {
            parser_key(name): adapter for name, adapter in build_core_parser_instances().items()
        }
        self.inspector_name = inspector_name

    def get(self, name: ParserName | str) -> MultimodalDocumentParser:
        key = parser_key(name)
        try:
            return self._parsers[key]
        except KeyError as exc:
            raise ParserError(
                "Parser is not registered",
                details={"parser": key, "available": sorted(self._parsers)},
            ) from exc

    def names(self) -> list[str]:
        return sorted(self._parsers)

    def register(self, name: str, parser: MultimodalDocumentParser) -> None:
        self._parsers[parser_key(name)] = parser


class ParseDocumentService:
    """Inspect, route, parse with fallbacks, and normalize."""

    def __init__(
        self,
        registry: ParserRegistry | None = None,
        router: AutomaticParserRouter | None = None,
        *,
        inspector_name: str | None = None,
    ) -> None:
        self._registry = registry or ParserRegistry()
        names = frozenset(self._registry.names())
        self._router = router or AutomaticParserRouter(registered_names=names)
        configured = inspector_name if inspector_name is not None else self._registry.inspector_name
        self._inspector_name = configured or resolve_inspector_name(names)

    async def inspect(self, source: ParseSource) -> ParserInspection:
        return await self._registry.get(self._inspector_name).inspect(source)

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
            key = parser_key(parser_name)
            parser = self._registry.get(key)
            attempted.append(key)
            try:
                raw = await parser.parse(source, opts)
                document = normalize_parser_result(raw, source)
                document.parser_info.attempted_parsers = attempted
                document.parser_info.warnings = list(raw.warnings) + warnings
                document.parser_info.profile = selection.profile.value
                return document, selection, attempted
            except Exception as exc:
                last_error = exc
                message = f"{key} failed: {exc}"
                warnings.append(message)
                logger.warning(
                    "parser_attempt_failed",
                    parser=key,
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
        parser_name: ParserName | str,
        options: ParseOptions | None = None,
    ) -> RawParserResult:
        parser = self._registry.get(parser_name)
        return await parser.parse(source, options or ParseOptions())


def parser_registry_from_settings(settings: object | None = None) -> ParserRegistry:
    """Build a registry from core + discovered parser plugins."""
    instances = build_parser_instances(settings, discover=True)
    inspector = resolve_inspector_name(
        instances,
        configured=configured_inspector_name(settings),
    )
    return ParserRegistry(parsers=instances, inspector_name=inspector)
