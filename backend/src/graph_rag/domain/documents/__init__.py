"""Normalized document aggregates and ingestion result contracts."""

from graph_rag.domain.documents.canonical_shards import (
    AssetArtifactRef,
    CanonicalCurrentPointer,
    CanonicalDocumentMetadata,
    CanonicalManifest,
    CanonicalPageArtifact,
    PageArtifactRef,
)
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
    "AssetArtifactRef",
    "CanonicalCurrentPointer",
    "CanonicalDocument",
    "CanonicalDocumentMetadata",
    "CanonicalManifest",
    "CanonicalPageArtifact",
    "DocumentAsset",
    "DocumentSection",
    "ElementReference",
    "IngestionResult",
    "IngestionStatus",
    "NormalizedDocument",
    "NormalizedPage",
    "PageArtifactRef",
    "ParserInfo",
]
