"""graphrag_inspect_document / graphrag_delete_document / graphrag_reindex_document.

Each mirrors its ``api/routes/documents.py`` counterpart's authorization
sequence exactly (fetch document -> 404 if missing -> require_action with the
document as the ABAC resource) before touching the service layer.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from graph_rag.application.authorization.gate import ensure_document_read, require_action
from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.deletion.stages import ReindexScope
from graph_rag.domain.ingestion.records import DocumentRecord
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import NotFoundError, ValidationError

INSPECT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_id": {"type": "string"},
        "show_chunks": {"type": "boolean", "default": False},
    },
    "required": ["document_id"],
}

DELETE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_id": {"type": "string"},
        "retain_postgres": {"type": "boolean", "default": False},
    },
    "required": ["document_id"],
}

REINDEX_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_id": {"type": "string"},
        "scope": {
            "type": "string",
            "enum": ["full", "vectors", "graph"],
            "default": "full",
        },
    },
    "required": ["document_id"],
}


async def _get_document_or_404(
    container: ServiceContainer, tenant: TenantContext, document_id: UUID
) -> DocumentRecord:
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    return document


async def inspect_document(
    container: ServiceContainer,
    tenant: TenantContext,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    document_id = UUID(arguments["document_id"])
    document = await _get_document_or_404(container, tenant, document_id)
    ensure_document_read(container.require_authorization(), tenant, document)
    payload: dict[str, Any] = document.model_dump(mode="json")
    if arguments.get("show_chunks"):
        chunks, total = await container.list_chunks(tenant, document_id, offset=0, limit=200)
        payload["chunks"] = [
            {
                "chunk_id": str(chunk.chunk_id),
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section": list(chunk.section_path),
                "modality": chunk.modality.value,
                "chunk_type": chunk.chunk_type.value,
                "token_count": chunk.token_count,
                "content": chunk.text[:1200],
            }
            for chunk in chunks
        ]
        payload["chunk_total"] = total
    return payload


async def delete_document(
    container: ServiceContainer,
    tenant: TenantContext,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    document_id = UUID(arguments["document_id"])
    document = await _get_document_or_404(container, tenant, document_id)
    require_action(
        container.require_authorization(), tenant, Action.DOCUMENT_DELETE, document=document
    )
    operation = await container.submit_deletion(tenant, document_id)
    await container.commit_db()
    result = operation.result
    return {
        "operation_id": str(operation.operation_id),
        "document_id": str(document_id),
        "status": operation.status,
        "vectors_deleted": result.vectors_deleted if result else None,
        "graph_deleted": result.graph_deleted if result else None,
        "objects_deleted": result.objects_deleted if result else None,
        "warnings": list(result.warnings) if result else [],
    }


async def reindex_document(
    container: ServiceContainer,
    tenant: TenantContext,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    scope_raw = str(arguments.get("scope", "full")).lower()
    try:
        scope = ReindexScope(scope_raw)
    except ValueError as exc:
        raise ValidationError(
            "scope must be one of: full, vectors, graph",
            details={"scope": scope_raw},
        ) from exc

    document_id = UUID(arguments["document_id"])
    document = await _get_document_or_404(container, tenant, document_id)
    require_action(
        container.require_authorization(), tenant, Action.DOCUMENT_REINDEX, document=document
    )
    result = await container.submit_reindex(tenant, document_id, scope=scope)
    await container.commit_db()
    return result.model_dump(mode="json")
