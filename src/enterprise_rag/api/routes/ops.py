"""Operations dashboard: live tenant metrics."""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.api.dependencies import ContainerDep, TenantDep
from enterprise_rag.infrastructure.observability import get_metrics

router = APIRouter(prefix="/ops", tags=["operations"])


class DashboardDocumentRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str | None = None
    status: str
    updated_at: str | None = None


class DashboardHealthItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    detail: str | None = None


class OpsDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents_total: int = 0
    documents_by_status: dict[str, int] = Field(default_factory=dict)
    failed_processing: int = 0
    processing: int = 0
    ready: int = 0
    queries_total: int = 0
    recent_documents: list[DashboardDocumentRow] = Field(default_factory=list)
    processing_health: list[DashboardHealthItem] = Field(default_factory=list)
    tenant_key: str | None = None
    tenant_label: str | None = None


@router.get("/dashboard", response_model=OpsDashboardResponse)
async def dashboard(tenant: TenantDep, container: ContainerDep) -> OpsDashboardResponse:
    docs: list[Any] = []
    if container.document_repo is not None:
        docs, _total = await container.document_repo.list_documents(
            tenant, limit=500, offset=0
        )

    status_counts: Counter[str] = Counter()
    for doc in docs:
        status = getattr(doc.status, "value", None) or str(doc.status)
        status_counts[status] += 1

    failed_keys = {"failed", "error", "dead_letter"}
    processing_keys = {"processing", "registered", "ingesting", "parsing", "chunking", "indexing"}
    ready_keys = {"ready", "indexed", "active"}

    failed = sum(count for key, count in status_counts.items() if key.lower() in failed_keys)
    processing = sum(
        count for key, count in status_counts.items() if key.lower() in processing_keys
    )
    ready = sum(count for key, count in status_counts.items() if key.lower() in ready_keys)

    recent = sorted(
        docs,
        key=lambda item: getattr(item, "updated_at", None) or getattr(item, "created_at", None) or "",
        reverse=True,
    )[:8]

    recent_rows = [
        DashboardDocumentRow(
            document_id=str(doc.document_id),
            title=doc.title,
            status=str(getattr(doc.status, "value", doc.status)),
            updated_at=(
                doc.updated_at.isoformat()
                if getattr(doc, "updated_at", None) is not None
                else None
            ),
        )
        for doc in recent
    ]

    flat = dict(container.metrics)
    flat.update(get_metrics().as_flat_counters())
    queries_total = int(
        flat.get("query_completed_total")
        or flat.get("queries_total")
        or flat.get("requests_total")
        or 0
    )

    health: list[DashboardHealthItem] = []
    for index, check in enumerate(container.ready_checks):
        name = getattr(check, "__name__", f"check_{index}")
        try:
            result = check()
            if hasattr(result, "__await__"):
                result = await result  # type: ignore[misc]
            ok = bool(result)
        except Exception as exc:  # noqa: BLE001
            health.append(
                DashboardHealthItem(name=name, status="down", detail=str(exc)[:160])
            )
            continue
        health.append(
            DashboardHealthItem(
                name=name,
                status="ok" if ok else "degraded",
                detail=None if ok else "readiness check returned false",
            )
        )
    if not health:
        health.append(DashboardHealthItem(name="api", status="ok", detail="no backend checks"))

    tenant_label = tenant.tenant_key
    if container.tenant_repo is not None:
        record = await container.tenant_repo.get_by_id(tenant.tenant_id)
        if record is not None:
            tenant_label = record.display_name or record.tenant_key

    return OpsDashboardResponse(
        documents_total=len(docs),
        documents_by_status=dict(status_counts),
        failed_processing=failed,
        processing=processing,
        ready=ready,
        queries_total=queries_total,
        recent_documents=recent_rows,
        processing_health=health,
        tenant_key=tenant.tenant_key,
        tenant_label=tenant_label,
    )
