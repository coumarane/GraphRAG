"""Document ingest/metadata/elements/graph/delete routes."""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import Response

from enterprise_rag.api.dependencies import ContainerDep, TenantDep
from enterprise_rag.api.schemas import (
    ChunkListResponse,
    ChunkPreviewItem,
    DeletionAcceptedResponse,
    DocumentListResponse,
    DocumentResponse,
    ElementItem,
    ElementListResponse,
    GraphViewResponse,
    IngestAcceptedResponse,
    ReprocessAcceptedResponse,
)
from enterprise_rag.application.ingestion.register_source import RegisterSourceRequest
from enterprise_rag.application.runtime.container import ServiceContainer
from enterprise_rag.domain.deletion.stages import ReindexScope
from enterprise_rag.domain.ingestion.records import DocumentRecord
from enterprise_rag.domain.ingestion.stages import DocumentLifecycleStatus
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import NotFoundError, ValidationError
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


async def _run_local_ingest(
    container: ServiceContainer,
    tenant: TenantContext,
    ingestion_run_id: UUID,
) -> None:
    try:
        await container.require_process_ingestion().execute(tenant, ingestion_run_id)
    except Exception:
        logger.exception(
            "background_ingest_failed",
            ingestion_run_id=str(ingestion_run_id),
            tenant_id=str(tenant.tenant_id),
        )


@router.post("/ingest", status_code=202, response_model=IngestAcceptedResponse)
async def ingest_document(
    tenant: TenantDep,
    container: ContainerDep,
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(default=None),
    source_url: str | None = Form(default=None),
    title: str | None = Form(default=None),
    document_type: str | None = Form(default=None),
    parser_requested: str | None = Form(default="auto"),
    tags: str | None = Form(default=None),
    security_labels: str | None = Form(default=None),
    force_new_version: bool = Form(default=False),
) -> IngestAcceptedResponse:
    container.metrics["requests_total"] = container.metrics.get("requests_total", 0) + 1
    service = container.require_register_source()
    tag_list = [part.strip() for part in (tags or "").split(",") if part.strip()]
    label_list = [
        part.strip() for part in (security_labels or "").split(",") if part.strip()
    ]

    tmp_path: Path | None = None
    try:
        local_path: str | None = None
        if file is not None and file.filename:
            suffix = Path(file.filename).suffix or ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(await file.read())
                tmp_path = Path(handle.name)
                local_path = str(tmp_path)
        result = await service.execute(
            tenant,
            RegisterSourceRequest(
                local_path=local_path,
                source_url=source_url,
                title=title or (file.filename if file else None),
                document_type=document_type,
                tags=tag_list,
                security_labels=label_list,
                parser_requested=parser_requested,
                force_new_version=force_new_version,
            ),
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    if container.auto_process_ingest and not result.duplicate_version:
        background_tasks.add_task(
            _run_local_ingest,
            container,
            tenant,
            result.ingestion_run_id,
        )

    return IngestAcceptedResponse(
        ingestion_run_id=result.ingestion_run_id,
        document_id=result.document_id,
        version_id=result.version_id,
        duplicate_version=result.duplicate_version,
    )


def _document_response(document: DocumentRecord) -> DocumentResponse:
    return DocumentResponse(
        document_id=document.document_id,
        tenant_id=document.tenant_id,
        title=document.title,
        document_type=document.document_type,
        status=document.status.value,
        current_version_id=document.current_version_id,
        tags=list(document.tags),
        security_labels=list(document.security_labels),
        metadata=dict(document.metadata),
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    tenant: TenantDep,
    container: ContainerDep,
    offset: int = 0,
    limit: int = 50,
) -> DocumentListResponse:
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")
    items, total = await container.require_document_repo().list_documents(
        tenant, offset=offset, limit=limit
    )
    return DocumentListResponse(
        items=[_document_response(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> DocumentResponse:
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    return _document_response(document)


@router.post(
    "/{document_id}/reprocess",
    status_code=202,
    response_model=ReprocessAcceptedResponse,
)
async def reprocess_document(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
    background_tasks: BackgroundTasks,
    scope: str = "full",
) -> ReprocessAcceptedResponse:
    """Re-index an already stored document without re-uploading the file."""
    try:
        reindex_scope = ReindexScope(scope.lower())
    except ValueError as exc:
        raise ValidationError(
            "scope must be one of: full, vectors, graph",
            details={"scope": scope},
        ) from exc

    result = await container.submit_reindex(
        tenant,
        document_id=document_id,
        scope=reindex_scope,
    )
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is not None:
        document.status = DocumentLifecycleStatus.INGESTING
        await container.require_document_repo().update_document(tenant, document)

    if (
        container.auto_process_ingest
        and result.ingestion_run_id is not None
        and reindex_scope in {ReindexScope.FULL, ReindexScope.VECTORS}
    ):
        background_tasks.add_task(
            _run_local_ingest,
            container,
            tenant,
            result.ingestion_run_id,
        )

    return ReprocessAcceptedResponse(
        operation_id=result.operation_id,
        document_id=result.document_id,
        version_id=result.version_id,
        ingestion_run_id=result.ingestion_run_id,
        scope=result.scope.value,
        status=result.status,
        vectors_cleared=result.vectors_cleared,
        graph_cleared=result.graph_cleared,
        warnings=list(result.warnings),
    )


@router.get("/{document_id}/chunks", response_model=ChunkListResponse)
async def list_document_chunks(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
    version_id: UUID | None = None,
    offset: int = 0,
    limit: int = 100,
) -> ChunkListResponse:
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    if limit < 1 or limit > 500:
        raise ValidationError("limit must be between 1 and 500")
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    chunks, total = await container.list_chunks(
        tenant,
        document_id,
        version_id=version_id,
        offset=offset,
        limit=limit,
    )
    return ChunkListResponse(
        items=[
            ChunkPreviewItem(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                version_id=chunk.version_id,
                chunk_type=chunk.chunk_type.value,
                modality=chunk.modality,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                section_path=list(chunk.section_path),
                text=chunk.text,
                token_count=chunk.token_count,
            )
            for chunk in chunks
        ],
        total=total,
        offset=offset,
        limit=limit,
        document_id=document_id,
        version_id=version_id or document.current_version_id,
    )


@router.get("/{document_id}/original")
async def download_original(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
    version_id: UUID | None = None,
) -> Response:
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    resolved_version = version_id or document.current_version_id
    if resolved_version is None:
        raise NotFoundError(
            "Document has no version to download",
            details={"document_id": str(document_id)},
        )
    version = await container.require_document_repo().get_version(tenant, resolved_version)
    if version is None or not version.original_object_key:
        raise NotFoundError(
            "Original object not found",
            details={"document_id": str(document_id), "version_id": str(resolved_version)},
        )
    data = await container.require_object_store().get_bytes(
        tenant, object_key=version.original_object_key
    )
    filename = version.source_filename or "document.bin"
    return Response(
        content=data,
        media_type=version.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=60",
        },
    )


@router.get("/{document_id}/elements", response_model=ElementListResponse)
async def list_elements(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
    version_id: UUID | None = None,
    page: int | None = None,
    modality: Modality | None = None,
    element_type: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> ElementListResponse:
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")
    # Ensure document exists for tenant.
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    items, total = await container.list_elements(
        tenant,
        document_id,
        version_id=version_id,
        page=page,
        modality=modality,
        element_type=element_type,
        offset=offset,
        limit=limit,
    )
    return ElementListResponse(
        items=[
            ElementItem(
                element_id=item.element_id,
                document_id=item.document_id,
                version_id=item.version_id,
                element_type=item.element_type,
                modality=item.modality,
                page_start=item.page_start,
                page_end=item.page_end,
                section_path=list(item.section_path),
                preview=item.preview,
            )
            for item in items
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{document_id}/graph", response_model=GraphViewResponse)
async def get_document_graph(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
    limit: int = 100,
) -> GraphViewResponse:
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    nodes: list[dict[str, object]] = []
    relationships: list[dict[str, object]] = []
    graph = container.graph_store
    if graph is not None:
        raw_nodes = getattr(graph, "nodes", None)
        raw_rels = getattr(graph, "relationships", None)
        if isinstance(raw_nodes, dict):
            for node in list(raw_nodes.values())[:limit]:
                if getattr(node, "tenant_id", None) != tenant.tenant_id:
                    continue
                props = dict(getattr(node, "properties", {}))
                if props.get("document_id") not in {None, str(document_id)}:
                    continue
                nodes.append(
                    {
                        "node_id": str(getattr(node, "node_id", "")),
                        "label": str(getattr(node, "label", "")),
                        "properties": props,
                    }
                )
        if isinstance(raw_rels, dict):
            for rel in list(raw_rels.values())[:limit]:
                if getattr(rel, "tenant_id", None) != tenant.tenant_id:
                    continue
                relationships.append(
                    {
                        "relationship_id": str(getattr(rel, "relationship_id", "")),
                        "type": str(getattr(rel, "relationship_type", "")),
                        "source_node_id": str(getattr(rel, "source_node_id", "")),
                        "target_node_id": str(getattr(rel, "target_node_id", "")),
                        "properties": dict(getattr(rel, "properties", {})),
                    }
                )
    return GraphViewResponse(
        document_id=document_id,
        nodes=nodes,  # type: ignore[arg-type]
        relationships=relationships,  # type: ignore[arg-type]
    )


@router.delete("/{document_id}", status_code=202, response_model=DeletionAcceptedResponse)
async def delete_document(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> DeletionAcceptedResponse:
    operation = await container.submit_deletion(tenant, document_id)
    result = operation.result
    return DeletionAcceptedResponse(
        operation_id=operation.operation_id,
        document_id=document_id,
        status=operation.status,
        vectors_deleted=result.vectors_deleted if result else None,
        graph_deleted=result.graph_deleted if result else None,
        objects_deleted=result.objects_deleted if result else None,
        warnings=list(result.warnings) if result else [],
    )
