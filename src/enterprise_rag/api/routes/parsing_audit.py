"""Parsing audit / ingestion report API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from enterprise_rag.api.dependencies import ContainerDep, TenantDep
from enterprise_rag.application.ingestion.compare_parse_reports import CompareParseReportsService
from enterprise_rag.domain.types import JsonValue
from enterprise_rag.shared.exceptions import NotFoundError
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/documents", tags=["parsing-audit"])


class IngestionRunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    ingestion_run_ids: list[UUID] = Field(default_factory=list)


@router.get("/{document_id}/ingestion-runs", response_model=IngestionRunListResponse)
async def list_ingestion_parse_runs(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> IngestionRunListResponse:
    repo = container.require_parsing_audit_repo()
    run_ids = await repo.list_run_ids(tenant, document_id=document_id)
    return IngestionRunListResponse(document_id=document_id, ingestion_run_ids=run_ids)


@router.get("/{document_id}/ingestion-runs/{run_id}/report")
async def get_parse_report(
    document_id: UUID,
    run_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, JsonValue]:
    repo = container.require_parsing_audit_repo()
    snapshot = await repo.get_snapshot(
        tenant, document_id=document_id, ingestion_run_id=run_id
    )
    if snapshot is None:
        raise NotFoundError(
            "Parse report not found",
            details={"document_id": str(document_id), "run_id": str(run_id)},
        )
    return snapshot.model_dump(mode="json")


@router.get("/{document_id}/ingestion-runs/{run_id}/pages")
async def get_parse_pages(
    document_id: UUID,
    run_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, JsonValue]:
    snapshot = await _require_snapshot(container, tenant, document_id, run_id)
    return {
        "document_id": str(document_id),
        "ingestion_run_id": str(run_id),
        "pages": [page.model_dump(mode="json") for page in snapshot.pages],
    }


@router.get("/{document_id}/ingestion-runs/{run_id}/pages/{page_number}")
async def get_parse_page(
    document_id: UUID,
    run_id: UUID,
    page_number: int,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, JsonValue]:
    snapshot = await _require_snapshot(container, tenant, document_id, run_id)
    for page in snapshot.pages:
        if page.page_number == page_number:
            elements = [
                el.model_dump(mode="json")
                for el in snapshot.elements
                if el.page_number == page_number
            ]
            return {
                "page": page.model_dump(mode="json"),
                "elements": elements,
            }
    raise NotFoundError(
        "Page parse report not found",
        details={"page_number": page_number, "run_id": str(run_id)},
    )


@router.get("/{document_id}/ingestion-runs/{run_id}/elements")
async def get_parse_elements(
    document_id: UUID,
    run_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
    status: str | None = Query(default=None),
    element_type: str | None = Query(default=None),
) -> dict[str, JsonValue]:
    snapshot = await _require_snapshot(container, tenant, document_id, run_id)
    items = snapshot.elements
    if status:
        items = [el for el in items if el.status.value == status]
    if element_type:
        items = [el for el in items if el.normalized_element_type == element_type]
    return {
        "document_id": str(document_id),
        "ingestion_run_id": str(run_id),
        "total": len(items),
        "elements": [el.model_dump(mode="json") for el in items],
    }


@router.get("/{document_id}/ingestion-runs/{run_id}/errors")
async def get_parse_errors(
    document_id: UUID,
    run_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, JsonValue]:
    snapshot = await _require_snapshot(container, tenant, document_id, run_id)
    errors = [i.model_dump(mode="json") for i in snapshot.issues if i.severity == "error"]
    losses = [i.model_dump(mode="json") for i in snapshot.content_losses]
    return {
        "document_id": str(document_id),
        "ingestion_run_id": str(run_id),
        "errors": errors,
        "content_losses": losses,
    }


@router.get("/{document_id}/ingestion-runs/{run_id}/warnings")
async def get_parse_warnings(
    document_id: UUID,
    run_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, JsonValue]:
    snapshot = await _require_snapshot(container, tenant, document_id, run_id)
    warnings = [i.model_dump(mode="json") for i in snapshot.issues if i.severity == "warning"]
    return {
        "document_id": str(document_id),
        "ingestion_run_id": str(run_id),
        "warnings": warnings,
    }


@router.get("/{document_id}/ingestion-runs/{run_id}/pipeline")
async def get_parse_pipeline(
    document_id: UUID,
    run_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, JsonValue]:
    snapshot = await _require_snapshot(container, tenant, document_id, run_id)
    return {
        "document_id": str(document_id),
        "ingestion_run_id": str(run_id),
        "stages": [s.model_dump(mode="json") for s in snapshot.stages],
        "routing_decisions": [d.model_dump(mode="json") for d in snapshot.routing_decisions],
    }


@router.get("/{document_id}/compare")
async def compare_parse_runs(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
    run_a: UUID = Query(...),
    run_b: UUID = Query(...),
) -> dict[str, JsonValue]:
    repo = container.require_parsing_audit_repo()
    diff = await CompareParseReportsService(repo).compare(
        tenant,
        document_id=document_id,
        run_a=run_a,
        run_b=run_b,
    )
    return diff.model_dump(mode="json")


async def _require_snapshot(container, tenant, document_id: UUID, run_id: UUID):
    repo = container.require_parsing_audit_repo()
    snapshot = await repo.get_snapshot(
        tenant, document_id=document_id, ingestion_run_id=run_id
    )
    if snapshot is None:
        raise NotFoundError(
            "Parse report not found",
            details={"document_id": str(document_id), "run_id": str(run_id)},
        )
    return snapshot
