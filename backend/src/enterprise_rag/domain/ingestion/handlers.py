"""Stage handler contracts for ingestion orchestration."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.domain.ingestion.stages import IngestionStageName
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.domain.types import JsonValue


class StageOutcomeStatus(StrEnum):
    """Handler-reported outcome before state-machine transition."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    SKIPPED = "skipped"
    FAILED = "failed"


class StageContext(BaseModel):
    """Mutable execution context shared across stages of one run."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    tenant: TenantContext
    ingestion_run_id: UUID
    document_id: UUID
    version_id: UUID
    content_hash: str
    config_fingerprint: str
    correlation_id: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class StageOutcome(BaseModel):
    """Result produced by a stage handler."""

    model_config = ConfigDict(extra="forbid")

    status: StageOutcomeStatus = StageOutcomeStatus.COMPLETED
    warning: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    pages_processed: int | None = Field(default=None, ge=0)
    elements_processed: int | None = Field(default=None, ge=0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class StageHandler(Protocol):
    """Executable unit for a single ingestion stage."""

    @property
    def stage(self) -> IngestionStageName:
        """Stage this handler implements."""
        ...

    async def execute(self, context: StageContext) -> StageOutcome:
        """Run the stage. Must be idempotent for a given context fingerprint."""
        ...
