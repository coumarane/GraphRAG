"""Helpers to build and persist usage events from model calls."""

from __future__ import annotations

from datetime import UTC, datetime

from graph_rag.application.usage.context import get_usage_context
from graph_rag.domain.billing.openai_pricing import OpenAIPricingTable, estimate_usd
from graph_rag.domain.ids import new_id
from graph_rag.domain.models.contracts import ModelRole, TokenUsage
from graph_rag.domain.usage.models import UsageCapability, UsageEvent
from graph_rag.domain.usage.protocols import UsageRecorder
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)


def capability_for_role(role: ModelRole | str | None) -> UsageCapability:
    """Map model role to OpenAI-style capability bucket."""
    value = getattr(role, "value", role) or ModelRole.ANSWER.value
    text = str(value).lower()
    if text == ModelRole.VISION.value:
        return UsageCapability.VISION
    if text == ModelRole.EMBEDDING.value:
        return UsageCapability.EMBEDDINGS
    return UsageCapability.CHAT_COMPLETIONS


def build_usage_event(
    *,
    provider: str,
    model_name: str,
    role: ModelRole | str,
    usage: TokenUsage | None,
    latency_ms: float | None = None,
    correlation_id: str | None = None,
    pricing: OpenAIPricingTable | None = None,
) -> UsageEvent | None:
    """Build a usage event from call metadata + request context."""
    ctx = get_usage_context()
    if ctx is None:
        return None
    tokens = usage or TokenUsage()
    prompt = int(tokens.prompt_tokens or 0)
    completion = int(tokens.completion_tokens or 0)
    total = int(tokens.total_tokens or (prompt + completion))
    cost, known = estimate_usd(model_name, prompt, completion, table=pricing)
    return UsageEvent(
        event_id=new_id(),
        tenant_id=ctx.tenant_id,
        created_at=datetime.now(UTC),
        capability=capability_for_role(role),
        provider=provider,
        model_name=model_name,
        role=str(getattr(role, "value", role)),
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        estimated_usd=cost,
        known_pricing=known,
        correlation_id=correlation_id or ctx.correlation_id,
        document_id=ctx.document_id,
        ingestion_run_id=ctx.ingestion_run_id,
        query_id=ctx.query_id,
        latency_ms=latency_ms,
        user_id=ctx.user_id,
    )


async def record_model_usage(
    recorder: UsageRecorder | None,
    *,
    provider: str,
    model_name: str,
    role: ModelRole | str,
    usage: TokenUsage | None,
    latency_ms: float | None = None,
    correlation_id: str | None = None,
    pricing: OpenAIPricingTable | None = None,
) -> UsageEvent | None:
    """Best-effort record of a model call; never raises to callers."""
    if recorder is None:
        return None
    try:
        event = build_usage_event(
            provider=provider,
            model_name=model_name,
            role=role,
            usage=usage,
            latency_ms=latency_ms,
            correlation_id=correlation_id,
            pricing=pricing,
        )
        if event is None:
            return None
        await recorder.record(event)
        return event
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "usage_record_failed",
            error=str(exc),
            model=model_name,
            provider=provider,
        )
        return None
