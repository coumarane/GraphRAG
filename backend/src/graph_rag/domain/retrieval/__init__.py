"""Retrieval and query domain contracts."""

from graph_rag.domain.retrieval.assembly import (
    assemble_context,
    chunk_to_evidence,
    hit_to_evidence,
)
from graph_rag.domain.retrieval.enums import RetrievalMode
from graph_rag.domain.retrieval.expansion import expand_parents_and_neighbors
from graph_rag.domain.retrieval.fusion import (
    deduplicate_evidence,
    normalize_scores,
    reciprocal_rank_fusion,
)
from graph_rag.domain.retrieval.intent import QueryAnalysis, analyze_query, normalize_question
from graph_rag.domain.retrieval.models import (
    GraphPath,
    QueryRequest,
    QueryResponse,
    RetrievalFilters,
    RetrievalRequest,
    RetrievalResult,
    RetrievedEvidence,
)
from graph_rag.domain.retrieval.protocols import (
    ChunkLookupStore,
    LexicalHit,
    LexicalSearchStore,
)

__all__ = [
    "ChunkLookupStore",
    "GraphPath",
    "LexicalHit",
    "LexicalSearchStore",
    "QueryAnalysis",
    "QueryRequest",
    "QueryResponse",
    "RetrievalFilters",
    "RetrievalMode",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievedEvidence",
    "analyze_query",
    "assemble_context",
    "chunk_to_evidence",
    "deduplicate_evidence",
    "expand_parents_and_neighbors",
    "hit_to_evidence",
    "normalize_question",
    "normalize_scores",
    "reciprocal_rank_fusion",
]
