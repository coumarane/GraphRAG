"""Domain models/protocols for cross-document search over metadata and extracted fields."""

from graph_rag.domain.document_search.models import (
    DocumentSearchHit,
    DocumentSearchQuery,
    DocumentSearchResult,
    FieldFilter,
    FieldFilterOperator,
)
from graph_rag.domain.document_search.protocols import DocumentSearchRepository

__all__ = [
    "DocumentSearchHit",
    "DocumentSearchQuery",
    "DocumentSearchRepository",
    "DocumentSearchResult",
    "FieldFilter",
    "FieldFilterOperator",
]
