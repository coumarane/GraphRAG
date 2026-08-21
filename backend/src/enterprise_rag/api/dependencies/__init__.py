"""FastAPI dependency providers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request

from enterprise_rag.application.authorization.service import subject_from_tenant
from enterprise_rag.application.runtime.container import ServiceContainer
from enterprise_rag.application.usage.context import UsageContext, set_usage_context
from enterprise_rag.config.settings import get_settings
from enterprise_rag.domain.auth.passwords import is_weak_jwt_secret
from enterprise_rag.domain.auth.tokens import parse_access_token
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.domain.types import JsonValue
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
    set_usage_context(
        UsageContext(
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
        )
    )
    return tenant


async def _enrich_subject(
    container: ServiceContainer,
    tenant: TenantContext,
    *,
    user_id: UUID | None = None,
    email: str | None = None,
    role: str | None = None,
    is_service: bool = False,
) -> TenantContext:
    """Load user/membership attributes from DB; never trust client security headers."""
    attrs: dict[str, JsonValue] = dict(tenant.attributes)
    membership_attrs: dict[str, JsonValue] = dict(tenant.membership_attributes)
    groups: list[str] = list(tenant.groups)
    status = tenant.user_status
    resolved_user_id = user_id or tenant.user_id
    roles = list(tenant.roles)
    if role and role not in roles:
        roles.append(role)

    user_repo = container.user_repo
    if user_repo is not None and (resolved_user_id is not None or email):
        user = None
        if resolved_user_id is not None:
            user = await user_repo.get_by_id(resolved_user_id)
        if user is None and email:
            user = await user_repo.get_by_email(email)
        if user is not None:
            resolved_user_id = user.user_id
            email = user.email
            status = user.status.value if hasattr(user.status, "value") else str(user.status)
            attrs = dict(user.attributes)
            if user.role == "admin":
                attrs.setdefault("admin", True)
            if user.role and user.role not in roles:
                roles.append(user.role)
            get_membership = getattr(user_repo, "get_membership", None)
            if callable(get_membership):
                membership = await get_membership(
                    user_id=user.user_id,
                    tenant_id=tenant.tenant_id,
                )
                if membership is not None:
                    membership_attrs = dict(membership.attributes)
                    for key, value in membership_attrs.items():
                        attrs.setdefault(key, value)
            raw_groups = attrs.get("groups")
            if isinstance(raw_groups, list):
                groups = [str(g) for g in raw_groups]

    return TenantContext(
        tenant_id=tenant.tenant_id,
        tenant_key=tenant.tenant_key,
        principal=email or tenant.principal,
        user_id=resolved_user_id,
        roles=tuple(roles),
        security_labels=tenant.security_labels,
        attributes=attrs,
        membership_attributes=membership_attrs,
        groups=tuple(groups),
        user_status=status,
        is_service=is_service,
    ).ensure_authorized()


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
            base = TenantContext(
                tenant_id=claims.tenant_id,
                tenant_key=claims.tenant_key,
                principal=claims.email,
                user_id=UUID(claims.sub) if claims.sub else None,
                roles=(claims.role,),
            )
            enriched = await _enrich_subject(
                container,
                base,
                user_id=UUID(claims.sub) if claims.sub else None,
                email=claims.email,
                role=claims.role,
            )
            # Touch subject helper so attributes are normalized consistently.
            _ = subject_from_tenant(enriched)
            return _bind_usage_context(enriched)

        service_key = (security.api_service_key or "").strip()
        if service_key and x_api_service_key and x_api_service_key == service_key:
            resolved = await container.resolve_tenant(
                tenant_id=_parse_tenant_uuid(x_tenant_id),
                tenant_key=x_tenant_key,
                principal=x_principal or "service",
            )
            enriched = await _enrich_subject(
                container,
                resolved.model_copy(update={"is_service": True}),
                is_service=True,
            )
            return _bind_usage_context(enriched)

        raise AuthenticationError(
            "Authentication required",
            details={"hint": "Login or provide a valid session / service key"},
        )

    resolved = await container.resolve_tenant(
        tenant_id=_parse_tenant_uuid(x_tenant_id),
        tenant_key=x_tenant_key,
        principal=x_principal,
    )
    return _bind_usage_context(resolved)


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
