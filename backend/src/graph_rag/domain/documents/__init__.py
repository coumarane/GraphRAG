"""Normalized document aggregates and ingestion result contracts."""

from graph_rag.domain.documents.components import (
    DocumentAsset,
    DocumentSection,
    ElementReference,
    NormalizedPage,
    ParserInfo,
)
from graph_rag.domain.documents.document import NormalizedDocument
from graph_rag.domain.documents.ingestion_result import IngestionResult, IngestionStatus

__all__ = [
    "DocumentAsset",
    "DocumentSection",
    "ElementReference",
    "IngestionResult",
    "IngestionStatus",
    "NormalizedDocument",
    "NormalizedPage",
    "ParserInfo",
]
