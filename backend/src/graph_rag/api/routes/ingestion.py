"""Ingestion run control routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from graph_rag.api.dependencies import ContainerDep, TenantDep
from graph_rag.api.schemas import IngestionRunResponse, StageProgressItem
from graph_rag.domain.ingestion.state_machine import IngestionStateMachine, StageRecord
from graph_rag.shared.exceptions import NotFoundError

router = APIRouter(prefix="/ingestion-runs", tags=["ingestion"])


def _run_response(run, stages) -> IngestionRunResponse:
    machine = IngestionStateMachine(
        stages={
            item.stage: StageRecord(
                stage=item.stage,
                status=item.status,
                attempt_count=item.attempt_count,
                idempotency_key=item.idempotency_key,
                config_fingerprint=item.config_fingerprint,
                warning=item.warning,
                error_code=item.error_code,
                error_message=item.error_message,
            )
            for item in stages
        },
        run_status=run.status,
        pages_processed=run.pages_processed,
        elements_processed=run.elements_processed,
    )
    progress = machine.progress()
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
        worker_id=run.worker_id,
        heartbeat_at=run.heartbeat_at,
        current_stage=progress.current_stage.value if progress.current_stage else None,
        estimated_completion_percent=progress.estimated_completion_percent,
        stages=[
            StageProgressItem(
                stage=stage.stage.value,
                status=stage.status.value,
                attempt_count=stage.attempt_count,
                warning=stage.warning,
                error_code=stage.error_code,
                error_message=stage.error_message,
                worker_id=stage.worker_id,
                heartbeat_at=stage.heartbeat_at,
                started_at=stage.started_at,
                completed_at=stage.completed_at,
            )
            for stage in stages
        ],
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


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
    return _run_response(run, stages)


@router.get("/{run_id}/events")
async def stream_ingestion_run(
    run_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> StreamingResponse:
    """Server-sent progress events. Polling GET remains the durable fallback."""
    import asyncio
    import json

    terminal = {
        "completed",
        "completed_with_warnings",
        "partial",
        "failed",
        "cancelled",
    }

    async def events():
        while True:
            repo = container.require_ingestion_repo()
            run = await repo.get_run(tenant, run_id)
            if run is None:
                yield 'event: error\ndata: {"error":"not_found"}\n\n'
                return
            stages = await repo.list_stages(tenant, run_id)
            payload = _run_response(run, stages).model_dump(mode="json")
            yield f"event: progress\ndata: {json.dumps(payload)}\n\n"
            if run.status.value in terminal:
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(events(), media_type="text/event-stream")


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
