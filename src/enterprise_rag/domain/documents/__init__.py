"""Normalized document aggregates and ingestion result contracts."""

from enterprise_rag.domain.documents.components import (
    DocumentAsset,
    DocumentSection,
    ElementReference,
    NormalizedPage,
    ParserInfo,
)
from enterprise_rag.domain.documents.document import NormalizedDocument
from enterprise_rag.domain.documents.ingestion_result import IngestionResult, IngestionStatus

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
