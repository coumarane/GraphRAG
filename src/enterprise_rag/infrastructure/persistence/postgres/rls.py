"""PostgreSQL row-level security session helpers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import TenantError

# GUC used by RLS policies created in Alembic migrations.
TENANT_GUC = "app.tenant_id"


async def set_tenant_context(session: AsyncSession, tenant: TenantContext) -> None:
    """Set the transaction-local tenant GUC used by RLS policies.

    Uses ``set_config(..., is_local => true)`` so the value is scoped to the
    current transaction. No-op on dialects that do not support PostgreSQL GUCs
    (for example SQLite unit tests).
    """
    tenant.ensure_authorized()
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect != "postgresql":
        return
    await session.execute(
        text("SELECT set_config(:guc, :tenant_id, true)"),
        {"guc": TENANT_GUC, "tenant_id": str(tenant.tenant_id)},
    )


async def clear_tenant_context(session: AsyncSession) -> None:
    """Clear the tenant GUC for the current transaction when on PostgreSQL."""
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect != "postgresql":
        return
    await session.execute(
        text("SELECT set_config(:guc, '', true)"),
        {"guc": TENANT_GUC},
    )


def require_matching_tenant(tenant: TenantContext, entity_tenant_id: UUID) -> None:
    """Fail closed when a record tenant does not match the authorized context."""
    tenant.ensure_authorized()
    if entity_tenant_id != tenant.tenant_id:
        raise TenantError(
            "Tenant isolation violation",
            details={
                "expected_tenant_id": str(tenant.tenant_id),
                "actual_tenant_id": str(entity_tenant_id),
            },
        )
