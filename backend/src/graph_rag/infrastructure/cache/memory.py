"""No-op and in-memory cache invalidators."""

from __future__ import annotations

from uuid import UUID

from graph_rag.domain.tenant import TenantContext


class NoOpCacheInvalidator:
    """Cache invalidator used when Redis is not configured."""

    async def invalidate_document(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID | None = None,
    ) -> int:
        _ = (tenant, document_id, version_id)
        return 0


class InMemoryCacheInvalidator:
    """Tracks invalidated keys for unit tests."""

    def __init__(self) -> None:
        self.invalidated: list[tuple[UUID, UUID, UUID | None]] = []

    async def invalidate_document(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID | None = None,
    ) -> int:
        self.invalidated.append((tenant.tenant_id, document_id, version_id))
        return 1
