"""Parsing domain: protocols, routing and normalization."""

from graph_rag.domain.parsing.boilerplate import (
    BoilerplateMatch,
    detect_boilerplate,
    reclassify_boilerplate_elements,
)
from graph_rag.domain.parsing.normalize import normalize_parser_result
from graph_rag.domain.parsing.protocols import DocumentInspector, MultimodalDocumentParser
from graph_rag.domain.parsing.routing import (
    DEFAULT_ROUTE_PROFILES,
    AutomaticParserRouter,
    ParserRouteProfile,
    recommend_from_inspection,
)
from graph_rag.domain.parsing.types import (
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
    "BoilerplateMatch",
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
    "detect_boilerplate",
    "normalize_parser_result",
    "reclassify_boilerplate_elements",
    "recommend_from_inspection",
]
