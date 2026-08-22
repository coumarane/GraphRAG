"""Quota plan / assignment / reservation models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.types import JsonValue


class QuotaMetric(StrEnum):
    DOCUMENTS = "documents"
    PAGES = "pages"
    STORAGE_BYTES = "storage_bytes"
    QUERIES = "queries"
    OCR_PAGES = "ocr_pages"
    VISION_CALLS = "vision_calls"
    LLM_TOKENS = "llm_tokens"
    EMBEDDING_TOKENS = "embedding_tokens"


class QuotaPeriod(StrEnum):
    DAY = "day"
    MONTH = "month"
    LIFETIME = "lifetime"


class QuotaPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    name: str
    description: str | None = None
    limits: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class QuotaAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignment_id: UUID
    tenant_id: UUID
    user_id: UUID | None = None
    plan_id: UUID
    period: QuotaPeriod = QuotaPeriod.MONTH
    overrides: dict[str, int] = Field(default_factory=dict)
    is_active: bool = True


class UsageCounter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counter_id: UUID
    tenant_id: UUID
    user_id: UUID | None = None
    metric: QuotaMetric
    period: QuotaPeriod
    period_key: str
    used: int = 0
    reserved: int = 0


class QuotaReservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reservation_id: UUID
    tenant_id: UUID
    user_id: UUID | None = None
    metric: QuotaMetric
    period: QuotaPeriod
    period_key: str
    quantity: int
    status: str = "reserved"
    created_at: datetime | None = None
