"""Cache invalidation port for deletion / reindex."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from graph_rag.domain.tenant import TenantContext


class CacheInvalidator(Protocol):
    """Invalidate ephemeral cache keys after lifecycle changes."""

    async def invalidate_document(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID | None = None,
    ) -> int:
        """Drop document-scoped cache entries. Returns removed key count."""
        ...
