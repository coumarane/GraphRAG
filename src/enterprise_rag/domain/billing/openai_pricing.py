"""Static OpenAI list-price table for estimated USD cost."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_RATES: dict[str, tuple[str, str]] = {
    "gpt-4o-mini": ("0.15", "0.60"),
    "gpt-4o": ("2.50", "10.00"),
    "gpt-4.1": ("2.00", "8.00"),
    "gpt-4.1-mini": ("0.40", "1.60"),
    "text-embedding-3-small": ("0.02", "0.0"),
    "text-embedding-3-large": ("0.13", "0.0"),
    "text-embedding-ada-002": ("0.10", "0.0"),
}


@dataclass(frozen=True, slots=True)
class ModelRate:
    """Per-model USD rates (per 1M tokens)."""

    input_per_1m_usd: Decimal
    output_per_1m_usd: Decimal


@dataclass(frozen=True, slots=True)
class OpenAIPricingTable:
    """Lookup table for OpenAI model rates."""

    models: dict[str, ModelRate]
    currency: str = "USD"
    updated: str | None = None

    def rate_for(self, model_name: str) -> ModelRate | None:
        key = (model_name or "").strip().lower()
        if not key:
            return None
        if key in self.models:
            return self.models[key]
        # Allow provider-prefixed ids like "openai/gpt-4o-mini".
        short = key.rsplit("/", 1)[-1]
        return self.models.get(short)


def _as_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _builtin_table() -> OpenAIPricingTable:
    models = {
        name: ModelRate(
            input_per_1m_usd=Decimal(inp),
            output_per_1m_usd=Decimal(out),
        )
        for name, (inp, out) in _DEFAULT_RATES.items()
    }
    return OpenAIPricingTable(models=models, currency="USD", updated="2026-08")


def load_openai_pricing(path: Path | None = None) -> OpenAIPricingTable:
    """Load pricing YAML when present; otherwise return built-in defaults."""
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    else:
        candidates.extend(
            [
                Path("config/openai_pricing.yaml"),
                Path(__file__).resolve().parents[4] / "config" / "openai_pricing.yaml",
            ]
        )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        raw = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            break
        models_raw = raw.get("models") or {}
        models: dict[str, ModelRate] = {}
        if isinstance(models_raw, dict):
            for name, rates in models_raw.items():
                if not isinstance(rates, dict):
                    continue
                models[str(name).strip().lower()] = ModelRate(
                    input_per_1m_usd=_as_decimal(rates.get("input_per_1m_usd", 0)),
                    output_per_1m_usd=_as_decimal(rates.get("output_per_1m_usd", 0)),
                )
        if models:
            return OpenAIPricingTable(
                models=models,
                currency=str(raw.get("currency") or "USD"),
                updated=str(raw.get("updated")) if raw.get("updated") else None,
            )
        break
    return _builtin_table()


@lru_cache(maxsize=1)
def get_default_pricing_table() -> OpenAIPricingTable:
    """Cached process-wide pricing table."""
    return load_openai_pricing()


def estimate_usd(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int = 0,
    *,
    table: OpenAIPricingTable | None = None,
) -> tuple[Decimal, bool]:
    """Estimate USD cost for a call.

    Returns ``(cost, known_model)``. Unknown models yield ``(0, False)``.
    """
    pricing = table or get_default_pricing_table()
    rate = pricing.rate_for(model_name)
    if rate is None:
        return Decimal("0"), False
    prompt = max(0, int(prompt_tokens))
    completion = max(0, int(completion_tokens))
    cost = (
        (Decimal(prompt) * rate.input_per_1m_usd)
        + (Decimal(completion) * rate.output_per_1m_usd)
    ) / Decimal("1000000")
    return cost.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP), True
