"""Ingestion run control routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from enterprise_rag.api.dependencies import ContainerDep, TenantDep
from enterprise_rag.api.schemas import IngestionRunResponse, StageProgressItem
from enterprise_rag.shared.exceptions import NotFoundError

router = APIRouter(prefix="/ingestion-runs", tags=["ingestion"])


@router.get("/{run_id}", response_model=IngestionRunResponse)
async def get_ingestion_run(
    run_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> IngestionRunResponse:
    repo = container.require_ingestion_repo()
    run = await repo.get_run(tenant, run_id)
    if run is None:
        raise NotFoundError("Ingestion run not found", details={"run_id": str(run_id)})
    stages = await repo.list_stages(tenant, run_id)
    return IngestionRunResponse(
        ingestion_run_id=run.ingestion_run_id,
        document_id=run.document_id,
        version_id=run.version_id,
        status=run.status.value,
        parser_requested=run.parser_requested,
        parser_used=run.parser_used,
        pages_processed=run.pages_processed,
        elements_processed=run.elements_processed,
        retry_count=run.retry_count,
        latest_warning=run.latest_warning,
        error_code=run.error_code,
        error_message=run.error_message,
        correlation_id=run.correlation_id,
        stages=[
            StageProgressItem(
                stage=stage.stage.value,
                status=stage.status.value,
                attempt_count=stage.attempt_count,
                warning=stage.warning,
                error_code=stage.error_code,
                error_message=stage.error_message,
            )
            for stage in stages
        ],
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.post("/{run_id}/resume", response_model=IngestionRunResponse)
async def resume_ingestion_run(
    run_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> IngestionRunResponse:
    await container.resume_run(tenant, run_id)
    return await get_ingestion_run(run_id, tenant, container)


@router.post("/{run_id}/cancel", response_model=IngestionRunResponse)
async def cancel_ingestion_run(
    run_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> IngestionRunResponse:
    await container.cancel_run(tenant, run_id)
    return await get_ingestion_run(run_id, tenant, container)
