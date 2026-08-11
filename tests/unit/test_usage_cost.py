"""Usage cost pricing, metering, and aggregation tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from enterprise_rag.application.usage.aggregate import aggregate_usage_events
from enterprise_rag.application.usage.context import usage_context
from enterprise_rag.application.usage.record import capability_for_role, record_model_usage
from enterprise_rag.domain.billing.openai_pricing import estimate_usd, get_default_pricing_table
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.models.contracts import (
    ChatMessage,
    EmbeddingRequest,
    GenerationRequest,
    MessageRole,
    ModelRole,
    TokenUsage,
)
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.domain.usage.models import UsageCapability, UsageEvent
from enterprise_rag.infrastructure.models.openai_direct import OpenAIChatModel, OpenAIEmbeddingModel
from enterprise_rag.infrastructure.persistence.memory.usage import InMemoryUsageRepository
from enterprise_rag.application.runtime.local import build_local_container
from enterprise_rag.api.app import create_app
from fastapi.testclient import TestClient


def test_estimate_usd_known_models() -> None:
    cost, known = estimate_usd("gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=0)
    assert known is True
    assert cost == Decimal("0.15")
    cost2, known2 = estimate_usd(
        "text-embedding-3-small", prompt_tokens=1_000_000, completion_tokens=0
    )
    assert known2 is True
    assert cost2 == Decimal("0.02")


def test_estimate_usd_unknown_model_is_zero() -> None:
    cost, known = estimate_usd("totally-unknown-model", 1000, 100)
    assert known is False
    assert cost == Decimal("0")


def test_pricing_table_loads_builtin_models() -> None:
    table = get_default_pricing_table()
    assert table.rate_for("gpt-4o") is not None
    assert table.rate_for("gpt-4.1-mini") is not None


def test_capability_for_role_mapping() -> None:
    assert capability_for_role(ModelRole.VISION) is UsageCapability.VISION
    assert capability_for_role(ModelRole.EMBEDDING) is UsageCapability.EMBEDDINGS
    assert capability_for_role(ModelRole.ANSWER) is UsageCapability.CHAT_COMPLETIONS


def test_aggregate_usage_events_daily_and_capability() -> None:
    tenant = new_id()
    day = date(2026, 8, 10)
    events = [
        UsageEvent(
            event_id=new_id(),
            tenant_id=tenant,
            created_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
            capability=UsageCapability.CHAT_COMPLETIONS,
            provider="openai",
            model_name="gpt-4o-mini",
            role="answer",
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            estimated_usd=Decimal("0.00045"),
        ),
        UsageEvent(
            event_id=new_id(),
            tenant_id=tenant,
            created_at=datetime(2026, 8, 11, 9, tzinfo=UTC),
            capability=UsageCapability.EMBEDDINGS,
            provider="openai",
            model_name="text-embedding-3-small",
            role="embedding",
            prompt_tokens=2000,
            completion_tokens=0,
            total_tokens=2000,
            estimated_usd=Decimal("0.00004"),
        ),
    ]
    summary = aggregate_usage_events(
        events,
        from_date=day,
        to_date=day + timedelta(days=1),
        month_start=date(2026, 8, 1),
    )
    assert summary.total_requests == 2
    assert summary.total_tokens == 3500
    assert abs(summary.total_spend_usd - 0.00049) < 1e-9
    assert len(summary.daily_spend) == 2
    caps = {row.capability: row for row in summary.by_capability}
    assert caps["chat_completions"].requests == 1
    assert caps["embeddings"].input_tokens == 2000


def test_aggregate_buckets_late_utc_evening_on_utc_day() -> None:
    """Events at 22:44 UTC must stay on that UTC day even in UTC+2 local zones."""
    tenant = new_id()
    events = [
        UsageEvent(
            event_id=new_id(),
            tenant_id=tenant,
            created_at=datetime(2026, 8, 11, 22, 44, tzinfo=UTC),
            capability=UsageCapability.VISION,
            provider="openai",
            model_name="gpt-4o-mini",
            role="vision",
            prompt_tokens=1000,
            completion_tokens=200,
            total_tokens=1200,
            estimated_usd=Decimal("0.01"),
        )
    ]
    summary = aggregate_usage_events(
        events,
        from_date=date(2026, 8, 11),
        to_date=date(2026, 8, 11),
        month_start=date(2026, 8, 1),
    )
    assert summary.total_requests == 1
    assert summary.total_spend_usd == 0.01
    by_day = {row.date: row for row in summary.daily_spend}
    assert by_day["2026-08-11"].requests == 1


def test_chat_and_embed_adapters_record_usage() -> None:
    repo = InMemoryUsageRepository()
    tenant = new_id()

    def chat_fn(messages, model_name, temperature):  # noqa: ANN001
        return "ok", TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    def embed_fn(texts: list[str]):
        return [[0.1, 0.2]], TokenUsage(prompt_tokens=8, completion_tokens=0, total_tokens=8)

    chat = OpenAIChatModel(chat_fn=chat_fn, usage_recorder=repo)
    embed = OpenAIEmbeddingModel(embed_fn=embed_fn, usage_recorder=repo)

    async def _run() -> None:
        with usage_context(tenant_id=tenant, query_id=new_id()):
            await chat.generate(
                GenerationRequest(
                    messages=[ChatMessage(role=MessageRole.USER, content="hi")],
                    role=ModelRole.ANSWER,
                )
            )
            await embed.embed(EmbeddingRequest(texts=["hello"]))

    asyncio.run(_run())
    assert len(repo.events) == 2
    roles = {event.role for event in repo.events}
    assert "answer" in roles
    assert "embedding" in roles
    assert all(event.estimated_usd >= 0 for event in repo.events)


def test_record_model_usage_noop_without_context() -> None:
    repo = InMemoryUsageRepository()

    async def _run() -> None:
        await record_model_usage(
            repo,
            provider="openai",
            model_name="gpt-4o-mini",
            role=ModelRole.ANSWER,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    asyncio.run(_run())
    assert repo.events == []


def test_ops_usage_endpoint_empty(monkeypatch) -> None:
    from enterprise_rag.config.settings import clear_settings_cache

    monkeypatch.setenv("AUTH_ENABLED", "false")
    clear_settings_cache()
    try:
        container = build_local_container()
        app = create_app(container)
        client = TestClient(app)
        response = client.get(
            "/api/v1/ops/usage",
            headers={"X-Tenant-Key": "demo", "X-Principal": "test"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total_spend_usd"] == 0.0
        assert body["total_requests"] == 0
        assert isinstance(body["daily_spend"], list)
    finally:
        clear_settings_cache()


def test_usage_repo_summarize_empty() -> None:
    repo = InMemoryUsageRepository()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo", principal="test")
    end = datetime.now(UTC)
    start = end - timedelta(days=13)
    month_start = datetime(end.year, end.month, 1, tzinfo=UTC)
    summary = asyncio.run(
        repo.summarize(tenant, start=start, end=end, month_start=month_start)
    )
    assert summary.total_requests == 0
    assert summary.total_spend_usd == 0.0
    assert len(summary.daily_spend) >= 1
