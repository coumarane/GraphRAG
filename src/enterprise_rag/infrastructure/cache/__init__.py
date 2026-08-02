"""Cache adapters."""

from enterprise_rag.infrastructure.cache.memory import (
    InMemoryCacheInvalidator,
    NoOpCacheInvalidator,
)

__all__ = ["InMemoryCacheInvalidator", "NoOpCacheInvalidator"]
