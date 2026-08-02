"""Parsing domain: protocols, routing and normalization."""

from enterprise_rag.domain.parsing.normalize import normalize_parser_result
from enterprise_rag.domain.parsing.protocols import DocumentInspector, MultimodalDocumentParser
from enterprise_rag.domain.parsing.routing import (
    DEFAULT_ROUTE_PROFILES,
    AutomaticParserRouter,
    ParserRouteProfile,
    recommend_from_inspection,
)
from enterprise_rag.domain.parsing.types import (
    OcrMode,
    PageInspection,
    ParseOptions,
    ParserInspection,
    ParserName,
    ParserProfile,
    ParserSelection,
    ParseSource,
    RawElement,
    RawPage,
    RawParserResult,
)

__all__ = [
    "DEFAULT_ROUTE_PROFILES",
    "AutomaticParserRouter",
    "DocumentInspector",
    "MultimodalDocumentParser",
    "OcrMode",
    "PageInspection",
    "ParseOptions",
    "ParseSource",
    "ParserInspection",
    "ParserName",
    "ParserProfile",
    "ParserRouteProfile",
    "ParserSelection",
    "RawElement",
    "RawPage",
    "RawParserResult",
    "normalize_parser_result",
    "recommend_from_inspection",
]
