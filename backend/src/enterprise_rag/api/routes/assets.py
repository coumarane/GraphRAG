"""Asset download / presign routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from enterprise_rag.api.dependencies import ContainerDep, TenantDep
from enterprise_rag.api.schemas import AssetResponse
from enterprise_rag.application.authorization.gate import require_action
from enterprise_rag.domain.authorization.models import Action
from enterprise_rag.shared.exceptions import NotFoundError

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
    expires_seconds: int = 300,
) -> AssetResponse:
    require_action(container.require_authorization(), tenant, Action.DOCUMENT_READ)
    object_key = container.assets.get((tenant.tenant_id, asset_id))
    if object_key is None:
        raise NotFoundError("Asset not found", details={"asset_id": str(asset_id)})
    # MinIO/object-store prefix isolation remains; ABAC gates document.read first.
    url = await container.require_object_store().presign_get(
        tenant,
        object_key=object_key,
        expires_seconds=expires_seconds,
    )
    return AssetResponse(asset_id=asset_id, url=url, expires_seconds=expires_seconds)
