"""FastAPI dependency providers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request

from enterprise_rag.application.runtime.container import ServiceContainer
from enterprise_rag.application.usage.context import UsageContext, set_usage_context
from enterprise_rag.config.settings import get_settings
from enterprise_rag.domain.auth.passwords import is_weak_jwt_secret
from enterprise_rag.domain.auth.tokens import parse_access_token
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ValidationError,
)


def get_container(request: Request) -> ServiceContainer:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, ServiceContainer):
        raise ConfigurationError("API service container is not configured")
    return container


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _bind_usage_context(tenant: TenantContext) -> TenantContext:
    set_usage_context(UsageContext(tenant_id=tenant.tenant_id))
    return tenant


async def get_tenant_context(
    request: Request,
    container: Annotated[ServiceContainer, Depends(get_container)],
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_tenant_key: Annotated[str | None, Header(alias="X-Tenant-Key")] = None,
    x_principal: Annotated[str | None, Header(alias="X-Principal")] = None,
    x_api_service_key: Annotated[str | None, Header(alias="X-Api-Service-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> TenantContext:
    settings = get_settings()
    security = settings.security

    if security.auth_enabled:
        if is_weak_jwt_secret(security.auth_jwt_secret):
            raise ConfigurationError(
                "AUTH_JWT_SECRET is missing or too weak for auth-enabled deployments"
            )
        cookie_token = request.cookies.get(security.auth_cookie_name)
        bearer = _extract_bearer(authorization)
        token = bearer or cookie_token
        if token:
            claims = parse_access_token(token, secret=security.auth_jwt_secret)
            return _bind_usage_context(
                TenantContext(
                    tenant_id=claims.tenant_id,
                    tenant_key=claims.tenant_key,
                    principal=claims.email,
                    roles=(claims.role,),
                ).ensure_authorized()
            )

        service_key = (security.api_service_key or "").strip()
        if service_key and x_api_service_key and x_api_service_key == service_key:
            return _bind_usage_context(
                await container.resolve_tenant(
                    tenant_id=_parse_tenant_uuid(x_tenant_id),
                    tenant_key=x_tenant_key,
                    principal=x_principal or "service",
                )
            )

        raise AuthenticationError(
            "Authentication required",
            details={"hint": "Login or provide a valid session / service key"},
        )

    return _bind_usage_context(
        await container.resolve_tenant(
            tenant_id=_parse_tenant_uuid(x_tenant_id),
            tenant_key=x_tenant_key,
            principal=x_principal,
        )
    )


def _parse_tenant_uuid(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise ValidationError(
            "Invalid X-Tenant-ID",
            details={"value": raw},
        ) from exc


ContainerDep = Annotated[ServiceContainer, Depends(get_container)]
TenantDep = Annotated[TenantContext, Depends(get_tenant_context)]
