"""Parsing audit persistence port and comparison types."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.domain.parsing.audit import ParsingAuditSnapshot
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.domain.types import JsonValue


class ParsingAuditRepository(Protocol):
    """Persist and load immutable parsing audit snapshots."""

    async def save_snapshot(
        self,
        tenant: TenantContext,
        snapshot: ParsingAuditSnapshot,
    ) -> ParsingAuditSnapshot:
        """Persist a completed run audit (insert-only; never overwrite)."""
        ...

    async def get_snapshot(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        ingestion_run_id: UUID,
    ) -> ParsingAuditSnapshot | None:
        """Load a full audit snapshot for one run."""
        ...

    async def list_run_ids(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
    ) -> list[UUID]:
        """List ingestion_run_ids that have parse reports for a document."""
        ...


class ParseReportDiff(BaseModel):
    """Document-level comparison of two ingestion parse reports."""

    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    run_a: UUID
    run_b: UUID
    document_deltas: dict[str, JsonValue] = Field(default_factory=dict)
    page_deltas: list[dict[str, JsonValue]] = Field(default_factory=list)
    element_deltas: list[dict[str, JsonValue]] = Field(default_factory=list)
    stage_deltas: list[dict[str, JsonValue]] = Field(default_factory=list)
    summary: dict[str, JsonValue] = Field(default_factory=dict)
