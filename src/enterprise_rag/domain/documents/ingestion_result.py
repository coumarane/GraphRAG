"""Ingestion result contract matching ``contracts/ingestion-result.schema.yaml``."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IngestionStatus(StrEnum):
    """Terminal or near-terminal ingestion outcomes."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IngestionResult(BaseModel):
    """Structured summary returned by ingestion CLI/API flows."""

    model_config = ConfigDict(extra="forbid")

    status: IngestionStatus
    tenant_id: str = Field(min_length=1)
    document_id: UUID
    version_id: UUID
    ingestion_run_id: UUID
    parser_requested: str | None = None
    parser_used: str = Field(min_length=1)
    pages: int | None = Field(default=None, ge=0)
    elements: dict[str, int] | None = None
    chunks: dict[str, int] | None = None
    graph: dict[str, int] | None = None
    vectors: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0.0)
    warnings: list[str] = Field(default_factory=list)
