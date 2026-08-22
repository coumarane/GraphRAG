"""Domain models for LLM / embedding usage metering."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UsageCapability(StrEnum):
    """OpenAI-style capability buckets for the usage dashboard."""

    CHAT_COMPLETIONS = "chat_completions"
    VISION = "vision"
    EMBEDDINGS = "embeddings"


class UsageEvent(BaseModel):
    """One metered model invocation."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    tenant_id: UUID
    created_at: datetime
    capability: UsageCapability
    provider: str
    model_name: str
    role: str
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_usd: Decimal = Field(default=Decimal("0"))
    known_pricing: bool = True
    correlation_id: str | None = None
    document_id: UUID | None = None
    ingestion_run_id: UUID | None = None
    query_id: UUID | None = None
    latency_ms: float | None = Field(default=None, ge=0.0)
    user_id: UUID | None = None


class DailySpendRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    spend_usd: float
    tokens: int
    requests: int


class CapabilitySpendRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str
    spend_usd: float
    tokens: int
    requests: int
    input_tokens: int


class ModelSpendRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_name: str
    spend_usd: float
    tokens: int
    requests: int


class UsageSummary(BaseModel):
    """Aggregated usage for a tenant date range."""

    model_config = ConfigDict(extra="forbid")

    from_date: str
    to_date: str
    total_spend_usd: float = 0.0
    total_tokens: int = 0
    total_requests: int = 0
    month_spend_usd: float = 0.0
    daily_spend: list[DailySpendRow] = Field(default_factory=list)
    by_capability: list[CapabilitySpendRow] = Field(default_factory=list)
    by_model: list[ModelSpendRow] = Field(default_factory=list)
