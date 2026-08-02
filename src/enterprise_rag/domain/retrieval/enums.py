"""Retrieval mode vocabulary matching query-response contracts."""

from __future__ import annotations

from enum import StrEnum


class RetrievalMode(StrEnum):
    """Supported retrieval strategies."""

    NAIVE = "naive"
    LOCAL = "local"
    GLOBAL = "global"
    HYBRID = "hybrid"
    MULTIMODAL = "multimodal"
    MIX = "mix"
    AUTO = "auto"
