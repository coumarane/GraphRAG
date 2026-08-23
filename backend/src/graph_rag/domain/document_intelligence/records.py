"""Persistence-facing domain records for Document Intelligence models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentIntelligenceModelFieldRecord(BaseModel):
    """One field in a custom Document Intelligence model's schema."""

    model_config = ConfigDict(extra="forbid")

    field_id: UUID
    model_id: UUID
    tenant_id: UUID
    name: str
    label: str
    field_type: str
    default_selected: bool = False
    sort_order: int = 0


class DocumentIntelligenceModelRecord(BaseModel):
    """Persisted custom Document Intelligence model (a saved field schema)."""

    model_config = ConfigDict(extra="forbid")

    model_id: UUID
    tenant_id: UUID
    model_key: str
    name: str
    model_type: str = "custom"
    version: str = "1.0"
    provider: str = "internal"
    is_builtin: bool = False
    created_by_user_id: UUID | None = None
    fields: list[DocumentIntelligenceModelFieldRecord] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
