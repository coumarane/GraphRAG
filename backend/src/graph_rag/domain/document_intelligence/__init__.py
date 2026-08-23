"""Domain records/protocols for Document Intelligence models, fields, and extraction runs."""

from graph_rag.domain.document_intelligence.protocols import (
    DocumentExtractionRepository,
    DocumentIntelligenceModelRepository,
)
from graph_rag.domain.document_intelligence.records import (
    DocumentExtractedFieldRecord,
    DocumentExtractionRunRecord,
    DocumentIntelligenceModelFieldRecord,
    DocumentIntelligenceModelRecord,
)

__all__ = [
    "DocumentExtractedFieldRecord",
    "DocumentExtractionRepository",
    "DocumentExtractionRunRecord",
    "DocumentIntelligenceModelFieldRecord",
    "DocumentIntelligenceModelRecord",
    "DocumentIntelligenceModelRepository",
]
