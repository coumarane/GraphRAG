"""Tenant isolation context required by every tenant-owned operation."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.types import JsonValue
from graph_rag.shared.exceptions import TenantError


class TenantContext(BaseModel):
    """Authorized tenant scope for storage, retrieval and model calls.

    ``tenant_id`` is the canonical storage key. ``tenant_key`` is an optional
    human-readable slug (for example ``demo``) used by trusted CLI flows.

    Security attributes are loaded server-side from the user/membership tables
    and must never be taken from client-supplied headers.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: UUID
    tenant_key: str | None = None
    principal: str | None = None
    user_id: UUID | None = None
    roles: tuple[str, ...] = ()
    security_labels: tuple[str, ...] = Field(default_factory=tuple)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    membership_attributes: dict[str, JsonValue] = Field(default_factory=dict)
    groups: tuple[str, ...] = Field(default_factory=tuple)
    user_status: str = "active"
    is_service: bool = False

    def ensure_authorized(self) -> TenantContext:
        """Return self or raise when the tenant identity is unusable."""
        if self.tenant_id.int == 0:
            raise TenantError(
                "Tenant context is missing a valid tenant_id",
                details={"tenant_key": self.tenant_key},
            )
        return self
