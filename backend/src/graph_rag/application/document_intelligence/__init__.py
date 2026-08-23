"""Document Intelligence model/field catalog (built-in + custom)."""

from graph_rag.application.document_intelligence.catalog import (
    BUILTIN_DOCUMENT_INTELLIGENCE_MODELS,
    builtin_model_by_key,
)
from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceIngestOptions,
    FieldType,
    ModelFieldSpec,
    ModelType,
)

__all__ = [
    "BUILTIN_DOCUMENT_INTELLIGENCE_MODELS",
    "DocumentIntelligenceIngestOptions",
    "FieldType",
    "ModelFieldSpec",
    "ModelType",
    "builtin_model_by_key",
]
