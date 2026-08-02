"""FastAPI dependency providers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request

from enterprise_rag.application.runtime.container import ServiceContainer
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import ConfigurationError, ValidationError


def get_container(request: Request) -> ServiceContainer:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, ServiceContainer):
        raise ConfigurationError("API service container is not configured")
    return container


async def get_tenant_context(
    container: Annotated[ServiceContainer, Depends(get_container)],
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_tenant_key: Annotated[str | None, Header(alias="X-Tenant-Key")] = None,
    x_principal: Annotated[str | None, Header(alias="X-Principal")] = None,
) -> TenantContext:
    tenant_uuid: UUID | None = None
    if x_tenant_id:
        try:
            tenant_uuid = UUID(x_tenant_id)
        except ValueError as exc:
            raise ValidationError(
                "Invalid X-Tenant-ID",
                details={"value": x_tenant_id},
            ) from exc
    return await container.resolve_tenant(
        tenant_id=tenant_uuid,
        tenant_key=x_tenant_key,
        principal=x_principal,
    )


ContainerDep = Annotated[ServiceContainer, Depends(get_container)]
TenantDep = Annotated[TenantContext, Depends(get_tenant_context)]
