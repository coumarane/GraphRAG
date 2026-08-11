"""Aggregate raw usage events into dashboard summary rows."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

from enterprise_rag.domain.usage.models import (
    CapabilitySpendRow,
    DailySpendRow,
    ModelSpendRow,
    UsageEvent,
    UsageSummary,
)


def _day_key(value: datetime) -> str:
    """Bucket events by UTC calendar day (matches API ``from``/``to`` query params)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.date().isoformat()


def aggregate_usage_events(
    events: list[UsageEvent],
    *,
    from_date: date,
    to_date: date,
    month_start: date,
) -> UsageSummary:
    """Build OpenAI-style usage aggregates from event rows."""
    daily: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"spend": Decimal("0"), "tokens": 0, "requests": 0}
    )
    by_cap: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"spend": Decimal("0"), "tokens": 0, "requests": 0, "input": 0}
    )
    by_model: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"spend": Decimal("0"), "tokens": 0, "requests": 0}
    )

    total_spend = Decimal("0")
    total_tokens = 0
    total_requests = 0
    month_spend = Decimal("0")

    # Ensure every day in range appears (zero-filled chart).
    cursor = from_date
    while cursor <= to_date:
        _ = daily[cursor.isoformat()]
        cursor = date.fromordinal(cursor.toordinal() + 1)

    for event in events:
        day = _day_key(event.created_at)
        event_day = date.fromisoformat(day)
        spend = event.estimated_usd if isinstance(event.estimated_usd, Decimal) else Decimal(
            str(event.estimated_usd)
        )
        tokens = int(event.total_tokens or 0)
        prompt = int(event.prompt_tokens or 0)

        if from_date <= event_day <= to_date:
            total_spend += spend
            total_tokens += tokens
            total_requests += 1
            daily[day]["spend"] = Decimal(str(daily[day]["spend"])) + spend
            daily[day]["tokens"] = int(daily[day]["tokens"]) + tokens
            daily[day]["requests"] = int(daily[day]["requests"]) + 1

            cap = event.capability.value if hasattr(event.capability, "value") else str(
                event.capability
            )
            by_cap[cap]["spend"] = Decimal(str(by_cap[cap]["spend"])) + spend
            by_cap[cap]["tokens"] = int(by_cap[cap]["tokens"]) + tokens
            by_cap[cap]["requests"] = int(by_cap[cap]["requests"]) + 1
            by_cap[cap]["input"] = int(by_cap[cap]["input"]) + prompt

            model = event.model_name or "unknown"
            by_model[model]["spend"] = Decimal(str(by_model[model]["spend"])) + spend
            by_model[model]["tokens"] = int(by_model[model]["tokens"]) + tokens
            by_model[model]["requests"] = int(by_model[model]["requests"]) + 1

        if event_day >= month_start:
            month_spend += spend

    daily_rows = [
        DailySpendRow(
            date=day,
            spend_usd=float(Decimal(str(vals["spend"]))),
            tokens=int(vals["tokens"]),
            requests=int(vals["requests"]),
        )
        for day, vals in sorted(daily.items(), key=lambda item: item[0])
    ]
    capability_rows = [
        CapabilitySpendRow(
            capability=cap,
            spend_usd=float(Decimal(str(vals["spend"]))),
            tokens=int(vals["tokens"]),
            requests=int(vals["requests"]),
            input_tokens=int(vals["input"]),
        )
        for cap, vals in sorted(by_cap.items(), key=lambda item: item[0])
    ]
    model_rows = sorted(
        [
            ModelSpendRow(
                model_name=model,
                spend_usd=float(Decimal(str(vals["spend"]))),
                tokens=int(vals["tokens"]),
                requests=int(vals["requests"]),
            )
            for model, vals in by_model.items()
        ],
        key=lambda row: row.spend_usd,
        reverse=True,
    )

    return UsageSummary(
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
        total_spend_usd=float(total_spend),
        total_tokens=total_tokens,
        total_requests=total_requests,
        month_spend_usd=float(month_spend),
        daily_spend=daily_rows,
        by_capability=capability_rows,
        by_model=model_rows,
    )
