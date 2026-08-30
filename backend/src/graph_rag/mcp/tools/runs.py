"""graphrag_show_run / graphrag_resume_run tool handlers.

Mirrors ``api/routes/ingestion.py`` exactly: neither route calls
``require_action`` -- tenant-scoped repository lookups (``repo.get_run(tenant,
run_id)``) are the only isolation for ingestion runs in this codebase today,
so these handlers don't invent a stricter check that doesn't exist elsewhere.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import NotFoundError

SHOW_RUN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"run_id": {"type": "string"}},
    "required": ["run_id"],
}

RESUME_RUN_INPUT_SCHEMA = SHOW_RUN_INPUT_SCHEMA


async def show_run(
    container: ServiceContainer,
    tenant: TenantContext,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    run_id = UUID(arguments["run_id"])
    repo = container.require_ingestion_repo()
    run = await repo.get_run(tenant, run_id)
    if run is None:
        raise NotFoundError("Ingestion run not found", details={"run_id": str(run_id)})
    stages = await repo.list_stages(tenant, run_id)
    return {
        "run": run.model_dump(mode="json"),
        "stages": [stage.model_dump(mode="json") for stage in stages],
    }


async def resume_run(
    container: ServiceContainer,
    tenant: TenantContext,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    run_id = UUID(arguments["run_id"])
    run = await container.resume_run(tenant, run_id)
    return dict(run.model_dump(mode="json"))
