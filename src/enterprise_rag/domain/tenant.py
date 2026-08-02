"""Tenant isolation context required by every tenant-owned operation."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.shared.exceptions import TenantError


class TenantContext(BaseModel):
    """Authorized tenant scope for storage, retrieval and model calls.

    ``tenant_id`` is the canonical storage key. ``tenant_key`` is an optional
    human-readable slug (for example ``demo``) used by trusted CLI flows.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: UUID
    tenant_key: str | None = None
    principal: str | None = None
    roles: tuple[str, ...] = ()
    security_labels: tuple[str, ...] = Field(default_factory=tuple)

    def ensure_authorized(self) -> TenantContext:
        """Return self or raise when the tenant identity is unusable."""
        if self.tenant_id.int == 0:
            raise TenantError(
                "Tenant context is missing a valid tenant_id",
                details={"tenant_key": self.tenant_key},
            )
        return self
