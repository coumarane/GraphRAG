"""Document Intelligence model/field catalog (built-in + custom) and extraction."""

from graph_rag.application.document_intelligence.catalog import (
    BUILTIN_DOCUMENT_INTELLIGENCE_MODELS,
    builtin_model_by_key,
)
from graph_rag.application.document_intelligence.models import (
    ConfidenceBand,
    DocumentExtractionRunStatus,
    DocumentIntelligenceExtractionRequest,
    DocumentIntelligenceExtractionResult,
    DocumentIntelligenceIngestOptions,
    ExtractedFieldResult,
    ExtractionMethod,
    FieldType,
    ModelFieldSpec,
    ModelType,
    confidence_band,
)
from graph_rag.application.document_intelligence.resolution import (
    ResolvedExtractionRequest,
    resolve_requested_fields,
)

__all__ = [
    "BUILTIN_DOCUMENT_INTELLIGENCE_MODELS",
    "ConfidenceBand",
    "DocumentExtractionRunStatus",
    "DocumentIntelligenceExtractionRequest",
    "DocumentIntelligenceExtractionResult",
    "DocumentIntelligenceIngestOptions",
    "ExtractedFieldResult",
    "ExtractionMethod",
    "FieldType",
    "ModelFieldSpec",
    "ModelType",
    "ResolvedExtractionRequest",
    "builtin_model_by_key",
    "confidence_band",
    "resolve_requested_fields",
]
