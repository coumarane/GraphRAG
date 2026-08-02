"""Document ingest/metadata/elements/graph/delete routes."""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile

from enterprise_rag.api.dependencies import ContainerDep, TenantDep
from enterprise_rag.api.schemas import (
    DeletionAcceptedResponse,
    DocumentResponse,
    ElementItem,
    ElementListResponse,
    GraphViewResponse,
    IngestAcceptedResponse,
)
from enterprise_rag.application.ingestion.register_source import RegisterSourceRequest
from enterprise_rag.domain.modality import Modality
from enterprise_rag.shared.exceptions import NotFoundError, ValidationError

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/ingest", status_code=202, response_model=IngestAcceptedResponse)
async def ingest_document(
    tenant: TenantDep,
    container: ContainerDep,
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

    return IngestAcceptedResponse(
        ingestion_run_id=result.ingestion_run_id,
        document_id=result.document_id,
        version_id=result.version_id,
        duplicate_version=result.duplicate_version,
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
