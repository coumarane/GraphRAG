"""Admin console HTTP API (simple-rag parity)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from graph_rag.api.dependencies import ContainerDep, TenantDep
from graph_rag.application.admin.console import AdminConsoleService
from graph_rag.application.authorization.gate import require_action
from graph_rag.config.settings import get_settings
from graph_rag.domain.authorization.models import Action

router = APIRouter(prefix="/admin/console", tags=["admin-console"])


class ConnectorWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    source_type: str | None = None
    description: str | None = None
    site_url: str | None = None
    enabled: bool | None = None


class CategoryWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    parser: str | None = None
    description: str | None = None
    color: str | None = None


class ChatContextWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    order: int | None = None
    visible: bool | None = None
    system_prompt: str | None = None


class SettingsWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parse_acceleration_mode: str | None = None
    pipeline_audit_enabled: bool | None = None
    semantic_cache_enabled: bool | None = None


class FeedbackWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    rating: str
    answer_excerpt: str = ""
    document_title: str | None = None
    citations_found: bool = True


class BenchmarkRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: str = Field(default="hybrid_rerank_k15")


def _console(container: ContainerDep, tenant: TenantDep) -> AdminConsoleService:
    require_action(container.require_authorization(), tenant, Action.ADMIN_SETTINGS)
    return container.require_admin_console()


def _dump(record: Any) -> dict[str, Any]:
    if hasattr(record, "model_dump"):
        return record.model_dump(mode="json")
    return dict(record)


@router.get("/connectors")
async def list_connectors(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    items = _console(container, tenant).list_connectors(tenant)
    return {"items": [_dump(item) for item in items]}


@router.post("/connectors", status_code=201)
async def create_connector(
    body: ConnectorWriteRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    record = _console(container, tenant).create_connector(
        tenant, body.model_dump(exclude_none=True)
    )
    return _dump(record)


@router.patch("/connectors/{connector_id}")
async def update_connector(
    connector_id: UUID,
    body: ConnectorWriteRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    record = _console(container, tenant).update_connector(
        tenant, connector_id, body.model_dump(exclude_none=True)
    )
    return _dump(record)


@router.delete("/connectors/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> None:
    _console(container, tenant).delete_connector(tenant, connector_id)


@router.post("/connectors/{connector_id}/test")
async def test_connector(
    connector_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    return _dump(_console(container, tenant).test_connector(tenant, connector_id))


@router.post("/connectors/{connector_id}/disable")
async def disable_connector(
    connector_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    record = _console(container, tenant).update_connector(tenant, connector_id, {"enabled": False})
    return _dump(record)


@router.get("/categories")
async def list_categories(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    items = _console(container, tenant).list_categories(tenant)
    return {"items": [_dump(item) for item in items]}


@router.post("/categories", status_code=201)
async def create_category(
    body: CategoryWriteRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    return _dump(
        _console(container, tenant).create_category(tenant, body.model_dump(exclude_none=True))
    )


@router.patch("/categories/{category_id}")
async def update_category(
    category_id: UUID,
    body: CategoryWriteRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    return _dump(
        _console(container, tenant).update_category(
            tenant, category_id, body.model_dump(exclude_none=True)
        )
    )


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> None:
    _console(container, tenant).delete_category(tenant, category_id)


@router.get("/chat-contexts")
async def list_chat_contexts(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    items = _console(container, tenant).list_chat_contexts(tenant)
    return {"items": [_dump(item) for item in items]}


@router.post("/chat-contexts", status_code=201)
async def create_chat_context(
    body: ChatContextWriteRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    return _dump(
        _console(container, tenant).create_chat_context(tenant, body.model_dump(exclude_none=True))
    )


@router.patch("/chat-contexts/{context_id}")
async def update_chat_context(
    context_id: UUID,
    body: ChatContextWriteRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    return _dump(
        _console(container, tenant).update_chat_context(
            tenant, context_id, body.model_dump(exclude_none=True)
        )
    )


@router.delete("/chat-contexts/{context_id}", status_code=204)
async def delete_chat_context(
    context_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> None:
    _console(container, tenant).delete_chat_context(tenant, context_id)


@router.get("/logs")
async def list_logs(
    tenant: TenantDep,
    container: ContainerDep,
    query: str | None = Query(default=None),
    level: str | None = Query(default=None),
    logger_name: str | None = Query(default=None, alias="logger"),
    correlation_id: str | None = Query(default=None),
    document_id: str | None = Query(default=None),
    pod: str | None = Query(default=None),
    from_ts: str | None = Query(default=None, alias="from"),
    until: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    _console(container, tenant)
    return container.require_admin_console().logs(
        query=query,
        level=level,
        logger_name=logger_name,
        correlation_id=correlation_id,
        document_id=document_id,
        pod=pod,
        from_ts=from_ts,
        until=until,
        limit=limit,
    )


@router.get("/document-health")
async def document_health(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).document_health(container, tenant)


@router.get("/processing")
async def processing(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).processing(container, tenant)


@router.get("/graph")
async def graph_insights(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return _console(container, tenant).graph_insights(container, tenant)


@router.post("/graph/consolidate")
async def consolidate_graph(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return _console(container, tenant).consolidate_duplicates(container, tenant)


@router.get("/feedback")
async def feedback_summary(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).feedback_summary(tenant)


@router.post("/feedback", status_code=201)
async def create_feedback(
    body: FeedbackWriteRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    return _dump(_console(container, tenant).add_feedback(tenant, body.model_dump()))


@router.get("/benchmarks")
async def list_benchmarks(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    items = _console(container, tenant).state(tenant).benchmarks
    return {"items": [_dump(item) for item in items]}


@router.post("/benchmarks/run")
async def run_benchmark(
    tenant: TenantDep,
    container: ContainerDep,
    body: BenchmarkRunRequest | None = None,
) -> dict[str, Any]:
    config = body.config if body is not None else "hybrid_rerank_k15"
    return _dump(_console(container, tenant).run_benchmark(tenant, config))


@router.get("/ingestion-audit")
async def ingestion_audit(
    tenant: TenantDep,
    container: ContainerDep,
    q: str | None = Query(default=None),
) -> dict[str, Any]:
    return await _console(container, tenant).ingestion_audit(container, tenant, query=q)


@router.get("/retrieval-audit")
async def retrieval_audit(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).retrieval_audit(container, tenant)


@router.get("/billing")
async def billing(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).billing(container, tenant)


@router.get("/cloud-costs")
async def cloud_costs(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).cloud_costs(container, tenant)


@router.get("/providers")
async def providers(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return _console(container, tenant).providers()


@router.post("/providers/{provider_id}/sync")
async def sync_provider(
    provider_id: str,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    payload = _console(container, tenant).providers()
    match = next((item for item in payload["items"] if item["id"] == provider_id), None)
    return {"status": "ok", "provider": match or {"id": provider_id}}


@router.get("/infrastructure")
async def infrastructure(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).infrastructure_with_counts(container, tenant)


@router.post("/infrastructure/cache/clear")
async def clear_semantic_cache(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    console = _console(container, tenant)
    state = console.state(tenant)
    state.cache_keys = 0
    state.cache_memory_bytes = 0
    return {"cleared": True}


@router.get("/settings")
async def get_settings_console(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    console = _console(container, tenant)
    settings = console.state(tenant).settings
    return {
        **_dump(settings),
        "danger_zone_enabled": console.danger_zone_enabled(),
        "environment": get_settings().app.environment,
    }


@router.patch("/settings")
async def patch_settings(
    body: SettingsWriteRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> dict[str, Any]:
    console = _console(container, tenant)
    settings = console.update_settings(tenant, body.model_dump(exclude_none=True))
    return {**_dump(settings), "danger_zone_enabled": console.danger_zone_enabled()}


@router.post("/danger/clear-chat")
async def danger_clear_chat(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).danger_clear_chat(container, tenant)


@router.post("/danger/wipe-graph")
async def danger_wipe_graph(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).danger_wipe_graph(container, tenant)


@router.post("/danger/wipe-vectors")
async def danger_wipe_vectors(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).danger_wipe_vectors(container, tenant)


@router.post("/danger/reprocess-all")
async def danger_reprocess_all(tenant: TenantDep, container: ContainerDep) -> dict[str, Any]:
    return await _console(container, tenant).danger_reprocess_all(container, tenant)
