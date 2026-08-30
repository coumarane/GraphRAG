"""Factory contract for capability plugins."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

TrustTier = Literal["core", "verified", "community"]


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    """Small factory object used by ``PluginRegistry``.

    Adapters stay untouched: metadata and construction live here, not on the
    infrastructure class.
    """

    plugin_name: str
    capability: str
    builder: Callable[[Any], Any]
    trust_tier: TrustTier = "community"
    config_model: type[BaseModel] | None = None
    extra: str | None = None
    modules: tuple[str, ...] = ()
    structured: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def build(self, settings: Any) -> Any:
        """Construct the adapter for ``settings``."""
        return self.builder(settings)
