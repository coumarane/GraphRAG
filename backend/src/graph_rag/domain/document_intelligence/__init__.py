"""Domain records/protocols for Document Intelligence models and fields."""

from graph_rag.domain.document_intelligence.protocols import DocumentIntelligenceModelRepository
from graph_rag.domain.document_intelligence.records import (
    DocumentIntelligenceModelFieldRecord,
    DocumentIntelligenceModelRecord,
)

__all__ = [
    "DocumentIntelligenceModelFieldRecord",
    "DocumentIntelligenceModelRecord",
    "DocumentIntelligenceModelRepository",
]
