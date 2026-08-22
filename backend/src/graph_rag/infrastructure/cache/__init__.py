"""Cache adapters."""

from graph_rag.infrastructure.cache.memory import (
    InMemoryCacheInvalidator,
    NoOpCacheInvalidator,
)

__all__ = ["InMemoryCacheInvalidator", "NoOpCacheInvalidator"]
