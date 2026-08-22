"""Ingestion application use cases."""

from graph_rag.application.ingestion.handlers import (
    CallableStageHandler,
    NoOpStageHandler,
    default_noop_handlers,
)
from graph_rag.application.ingestion.orchestrator import (
    IngestionOrchestrator,
    OrchestrationResult,
)
from graph_rag.application.ingestion.register_source import (
    RegisterSourceRequest,
    RegisterSourceResult,
    RegisterSourceService,
)

__all__ = [
    "CallableStageHandler",
    "IngestionOrchestrator",
    "NoOpStageHandler",
    "OrchestrationResult",
    "RegisterSourceRequest",
    "RegisterSourceResult",
    "RegisterSourceService",
    "default_noop_handlers",
]
