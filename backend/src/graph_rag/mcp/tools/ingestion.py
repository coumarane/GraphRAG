"""graphrag_ingest tool handler.

URL-only by design: an external MCP client requesting an arbitrary
server-local path would be a path-traversal-shaped risk distinct from the
tenant-scoping one this package otherwise guards against. Local-path ingest
remains a CLI-only capability.

``RegisterSourceService`` self-enforces ``Action.DOCUMENT_UPLOAD`` and the
``QuotaMetric.DOCUMENTS`` reservation internally when authorization/quotas are
wired (see ``application/ingestion/register_source.py`` and
``application/runtime/local.py``) -- this handler must not re-wrap it with
its own ``require_action`` call, or the check would (harmlessly but
redundantly) double-fire.
"""

from __future__ import annotations

from typing import Any

from graph_rag.application.ingestion.register_source import RegisterSourceRequest
from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.domain.tenant import TenantContext

INGEST_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source_url": {"type": "string", "format": "uri"},
        "title": {"type": "string"},
        "document_type": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "security_labels": {"type": "array", "items": {"type": "string"}},
        "force_new_version": {"type": "boolean", "default": False},
    },
    "required": ["source_url"],
}


async def ingest(
    container: ServiceContainer,
    tenant: TenantContext,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    service = container.require_register_source()
    result = await service.execute(
        tenant,
        RegisterSourceRequest(
            source_url=arguments["source_url"],
            title=arguments.get("title"),
            document_type=arguments.get("document_type"),
            tags=list(arguments.get("tags") or []),
            security_labels=list(arguments.get("security_labels") or []),
            parser_requested="auto",
            force_new_version=bool(arguments.get("force_new_version", False)),
        ),
    )

    if container.auto_process_ingest and not result.duplicate_version:
        await container.require_process_ingestion().execute(tenant, result.ingestion_run_id)
    elif container.outbox_store is not None and not result.duplicate_version:
        from graph_rag.application.ingestion.enqueue import enqueue_ingest_ids

        run = await container.require_ingestion_repo().get_run(tenant, result.ingestion_run_id)
        await enqueue_ingest_ids(
            container.outbox_store,
            tenant=tenant,
            ingestion_run_id=result.ingestion_run_id,
            document_id=result.document_id,
            version_id=result.version_id,
            content_hash=(run.content_hash or "") if run is not None else "",
            config_fingerprint=(run.config_fingerprint or "") if run is not None else "",
            correlation_id=run.correlation_id if run is not None else None,
        )

    await container.commit_db()
    return {
        "ingestion_run_id": str(result.ingestion_run_id),
        "document_id": str(result.document_id),
        "version_id": str(result.version_id),
        "duplicate_version": result.duplicate_version,
    }
