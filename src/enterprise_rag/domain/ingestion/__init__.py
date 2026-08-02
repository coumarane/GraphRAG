"""Ingestion lifecycle domain: stages, state machine and persistence ports."""

from enterprise_rag.domain.ingestion.handlers import (
    StageContext,
    StageHandler,
    StageOutcome,
    StageOutcomeStatus,
)
from enterprise_rag.domain.ingestion.protocols import (
    DocumentRepository,
    IngestionRepository,
    TenantRepository,
)
from enterprise_rag.domain.ingestion.queue import DeadLetterStore, IngestionTaskQueue
from enterprise_rag.domain.ingestion.records import (
    DocumentRecord,
    DocumentVersionRecord,
    IngestionRunRecord,
    IngestionStageRecord,
    ParserAttemptRecord,
    TenantRecord,
)
from enterprise_rag.domain.ingestion.retry import (
    DeadLetterRecord,
    IngestionTaskMessage,
    RetryPolicy,
    is_retryable_exception,
)
from enterprise_rag.domain.ingestion.stages import (
    INGESTION_STAGE_ORDER,
    STAGE_WEIGHTS,
    DocumentLifecycleStatus,
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
)
from enterprise_rag.domain.ingestion.state_machine import (
    IngestionProgress,
    IngestionStateMachine,
    StageRecord,
    build_persisted_stage_records,
    initial_stage_records,
)

__all__ = [
    "INGESTION_STAGE_ORDER",
    "STAGE_WEIGHTS",
    "DeadLetterRecord",
    "DeadLetterStore",
    "DocumentLifecycleStatus",
    "DocumentRecord",
    "DocumentRepository",
    "DocumentVersionRecord",
    "IngestionProgress",
    "IngestionRepository",
    "IngestionRunRecord",
    "IngestionRunStatus",
    "IngestionStageName",
    "IngestionStageRecord",
    "IngestionStateMachine",
    "IngestionTaskMessage",
    "IngestionTaskQueue",
    "ParserAttemptRecord",
    "RetryPolicy",
    "StageContext",
    "StageHandler",
    "StageOutcome",
    "StageOutcomeStatus",
    "StageRecord",
    "StageStatus",
    "TenantRecord",
    "TenantRepository",
    "build_persisted_stage_records",
    "initial_stage_records",
    "is_retryable_exception",
]
