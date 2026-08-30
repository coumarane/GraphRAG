"""Operations dashboard: live tenant metrics and OpenAI-style usage."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from graph_rag.api.dependencies import ContainerDep, TenantDep
from graph_rag.application.authorization.gate import require_action
from graph_rag.application.config_composer import (
    ConfigPreviewRequest,
    ConfigPreviewResponse,
    CurrentConfigResponse,
    build_current_config,
    preview_config_change,
)
from graph_rag.application.plugins.catalog import PluginCatalog, build_plugin_catalog
from graph_rag.application.plugins.mcp_ops import McpOpsStatus, build_mcp_ops_status
from graph_rag.config.settings import get_settings
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.usage.models import (
    CapabilitySpendRow,
    DailySpendRow,
    ModelSpendRow,
    UsageSummary,
)
from graph_rag.infrastructure.observability import get_metrics

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
    processing_keys = {
        "processing",
        "registered",
        "ingesting",
        "parsing",
        "chunking",
        "indexing",
    }
    ready_keys = {"ready", "indexed", "active"}

    failed = sum(count for key, count in status_counts.items() if key.lower() in failed_keys)
    processing = sum(
        count for key, count in status_counts.items() if key.lower() in processing_keys
    )
    ready = sum(count for key, count in status_counts.items() if key.lower() in ready_keys)

    recent = sorted(
        docs,
        key=lambda item: getattr(item, "updated_at", None)
        or getattr(item, "created_at", None)
        or "",
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


@router.get("/plugins", response_model=PluginCatalog)
async def list_plugins(tenant: TenantDep, container: ContainerDep) -> PluginCatalog:
    """List registered and allowlist-blocked plugins for operators."""
    require_action(container.require_authorization(), tenant, Action.ADMIN_PLUGINS)
    return build_plugin_catalog(get_settings())


@router.get("/mcp", response_model=McpOpsStatus)
async def mcp_status(tenant: TenantDep, container: ContainerDep) -> McpOpsStatus:
    """List MCP tools and connect hints for operators."""
    require_action(container.require_authorization(), tenant, Action.ADMIN_PLUGINS)
    return build_mcp_ops_status()


@router.get("/config-composer", response_model=CurrentConfigResponse)
async def get_config_composer(tenant: TenantDep, container: ContainerDep) -> CurrentConfigResponse:
    """Current effective chunking/retrieval config for operators to compose from."""
    require_action(container.require_authorization(), tenant, Action.ADMIN_SETTINGS)
    return build_current_config(get_settings())


@router.post("/config-composer/preview", response_model=ConfigPreviewResponse)
async def preview_config_composer(
    tenant: TenantDep,
    container: ContainerDep,
    body: ConfigPreviewRequest,
) -> ConfigPreviewResponse:
    """Validate a proposed chunking/retrieval override and render a YAML diff.

    Never writes to disk or to the running process's settings -- the operator
    copies the diff into a PR through the normal review/CI/ArgoCD path.
    """
    require_action(container.require_authorization(), tenant, Action.ADMIN_SETTINGS)
    return preview_config_change(get_settings(), body)


class UsageDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_date: str
    to_date: str
    total_spend_usd: float = 0.0
    total_tokens: int = 0
    total_requests: int = 0
    month_spend_usd: float = 0.0
    daily_spend: list[DailySpendRow] = Field(default_factory=list)
    by_capability: list[CapabilitySpendRow] = Field(default_factory=list)
    by_model: list[ModelSpendRow] = Field(default_factory=list)


def _parse_day(raw: str | None, *, default: date) -> date:
    if not raw:
        return default
    return date.fromisoformat(raw)


@router.get("/usage", response_model=UsageDashboardResponse)
async def usage_dashboard(
    tenant: TenantDep,
    container: ContainerDep,
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
) -> UsageDashboardResponse:
    """OpenAI-style usage aggregates for the current tenant."""
    today = datetime.now(UTC).date()
    end = _parse_day(to_date, default=today)
    start = _parse_day(from_date, default=end - timedelta(days=13))
    if start > end:
        start, end = end, start
    month_start = date(end.year, end.month, 1)

    start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, 999999, tzinfo=UTC)
    month_dt = datetime(month_start.year, month_start.month, month_start.day, tzinfo=UTC)

    repo = container.usage_repo
    if repo is None:
        empty = UsageSummary(from_date=start.isoformat(), to_date=end.isoformat())
        return UsageDashboardResponse(**empty.model_dump())

    summary = await repo.summarize(
        tenant,
        start=start_dt,
        end=end_dt,
        month_start=month_dt,
    )
    return UsageDashboardResponse(**summary.model_dump())
