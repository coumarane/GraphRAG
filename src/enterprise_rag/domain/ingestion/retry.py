"""Retry policy and dead-letter records for ingestion workers."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.ingestion.stages import IngestionStageName
from enterprise_rag.domain.types import JsonValue
from enterprise_rag.shared.exceptions import PermanentError, TransientError


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential backoff with optional jitter."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 30.0
    jitter: bool = True

    def should_retry(self, *, attempt_count: int, retryable: bool) -> bool:
        if not retryable:
            return False
        return attempt_count < self.max_attempts

    def delay_for(self, attempt_count: int) -> float:
        exponent = max(0, attempt_count - 1)
        delay = min(self.max_delay_seconds, self.base_delay_seconds * (2**exponent))
        if self.jitter:
            delay = float(delay * (0.5 + random.random()))  # noqa: S311
        return float(delay)


def is_retryable_exception(exc: BaseException) -> bool:
    """Classify exceptions for retry vs dead-letter."""
    if isinstance(exc, TransientError):
        return True
    return not isinstance(exc, PermanentError)


class DeadLetterRecord(BaseModel):
    """Poison-message / exhausted-retry record."""

    model_config = ConfigDict(extra="forbid")

    dead_letter_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    ingestion_run_id: UUID
    stage: IngestionStageName
    attempt_count: int = Field(ge=0)
    error_code: str
    error_message: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IngestionTaskMessage(BaseModel):
    """Queue message for asynchronous ingestion execution."""

    model_config = ConfigDict(extra="forbid")

    task_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    ingestion_run_id: UUID
    document_id: UUID
    version_id: UUID
    content_hash: str
    config_fingerprint: str
    correlation_id: str | None = None
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    attempt_count: int = Field(default=0, ge=0)
