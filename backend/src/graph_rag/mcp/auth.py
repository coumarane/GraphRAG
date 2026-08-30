"""Tenant resolution for MCP callers.

Tenant identity must never travel as an MCP tool-call argument: the
``tools/call`` JSON-RPC payload is model-generated / prompt-injectable, and
this codebase otherwise treats client-supplied identity as untrusted
(``api/dependencies/__init__.py``'s ``_enrich_subject``: "never trust client
security headers"). Instead, one MCP connection resolves to one fixed tenant,
from the same trusted ``X-Api-Service-Key`` + ``X-Tenant-*`` header path the
HTTP API already uses -- set once per connection, never per tool call.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from uuid import UUID

from starlette.types import Scope

from graph_rag.api.dependencies import resolve_service_tenant
from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.config.settings import get_settings
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import AuthenticationError, ValidationError

_current_tenant: ContextVar[TenantContext | None] = ContextVar("mcp_current_tenant", default=None)


def current_tenant() -> TenantContext:
    """Return the tenant resolved for the in-flight MCP connection."""
    tenant = _current_tenant.get()
    if tenant is None:
        raise AuthenticationError("MCP request has no resolved tenant")
    return tenant


def bind_tenant(tenant: TenantContext) -> Token[TenantContext | None]:
    return _current_tenant.set(tenant)


def reset_tenant(token: Token[TenantContext | None]) -> None:
    _current_tenant.reset(token)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            return str(value.decode("latin-1"))
    return None


def _parse_tenant_uuid(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise ValidationError("Invalid X-Tenant-ID", details={"value": raw}) from exc


async def resolve_tenant_from_scope(
    container: ServiceContainer,
    scope: Scope,
) -> TenantContext:
    """Resolve a tenant from static per-connection ASGI headers.

    Mirrors the ``X-Api-Service-Key`` branch of
    ``api/dependencies/get_tenant_context`` -- JWT/cookie auth is not usable
    here (no browser session for stdio/SSE-style clients), so MCP access
    requires service-key provisioning. This is a known v1 limitation, not an
    oversight.
    """
    settings = get_settings()
    service_key = (settings.security.api_service_key or "").strip()
    provided_key = _header(scope, b"x-api-service-key")
    if not service_key or not provided_key or provided_key != service_key:
        raise AuthenticationError(
            "MCP access requires a valid X-Api-Service-Key header",
            details={"hint": "Set X-Api-Service-Key and X-Tenant-ID in the MCP client config"},
        )
    return await resolve_service_tenant(
        container,
        tenant_id=_parse_tenant_uuid(_header(scope, b"x-tenant-id")),
        tenant_key=_header(scope, b"x-tenant-key"),
        principal=_header(scope, b"x-principal"),
    )
