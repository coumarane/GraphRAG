"""Normalized document aggregates and ingestion result contracts."""

from graph_rag.domain.documents.components import (
    DocumentAsset,
    DocumentSection,
    ElementReference,
    NormalizedPage,
    ParserInfo,
)
from graph_rag.domain.documents.document import CanonicalDocument, NormalizedDocument
from graph_rag.domain.documents.ingestion_result import IngestionResult, IngestionStatus

__all__ = [
    "CanonicalDocument",
    "DocumentAsset",
    "DocumentSection",
    "ElementReference",
    "IngestionResult",
    "IngestionStatus",
    "NormalizedDocument",
    "NormalizedPage",
    "ParserInfo",
]
