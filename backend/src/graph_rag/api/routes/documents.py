"""Document ingest/metadata/elements/graph/delete routes."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError as PydanticValidationError

from graph_rag.api.dependencies import ContainerDep, TenantDep
from graph_rag.api.schemas import (
    ChunkListResponse,
    ChunkPreviewItem,
    DeletionAcceptedResponse,
    DocumentExtractionListResponse,
    DocumentExtractionRunItem,
    DocumentListResponse,
    DocumentResponse,
    ElementItem,
    ElementListResponse,
    ExtractedFieldItem,
    GraphViewResponse,
    IngestAcceptedResponse,
    IngestionRunResponse,
    PageBoundingBox,
    PageElementItem,
    PageLayoutResponse,
    ReprocessAcceptedResponse,
    ReprocessRequest,
)
from graph_rag.application.authorization.filters import filter_authorized_documents
from graph_rag.application.authorization.gate import ensure_document_read, require_action
from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceIngestOptions,
)
from graph_rag.application.ingestion.register_source import RegisterSourceRequest
from graph_rag.application.ingestion.stage_pipeline import artifact_key
from graph_rag.application.ingestion.visual_enrichment import render_visual_png
from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.deletion.stages import ReindexScope
from graph_rag.domain.document_intelligence.records import (
    DocumentExtractedFieldRecord,
    DocumentExtractionRunRecord,
)
from graph_rag.domain.documents.document import NormalizedDocument
from graph_rag.domain.elements.base import ElementBase
from graph_rag.domain.ingestion.records import DocumentRecord
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus
from graph_rag.domain.modality import Modality
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import NotFoundError, ValidationError
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def _parse_document_intelligence_options(
    raw: str | None,
) -> DocumentIntelligenceIngestOptions | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("document_intelligence must be a JSON object") from exc
    try:
        return DocumentIntelligenceIngestOptions.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError(
            "document_intelligence is invalid", details={"errors": exc.errors()}
        ) from exc


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
    document_intelligence: str | None = Form(default=None),
) -> IngestAcceptedResponse:
    container.metrics["requests_total"] = container.metrics.get("requests_total", 0) + 1
    service = container.require_register_source()
    tag_list = [part.strip() for part in (tags or "").split(",") if part.strip()]
    label_list = [part.strip() for part in (security_labels or "").split(",") if part.strip()]
    document_intelligence_options = _parse_document_intelligence_options(document_intelligence)

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
                source_filename=file.filename if file and file.filename else None,
                document_type=document_type,
                tags=tag_list,
                security_labels=label_list,
                parser_requested=parser_requested,
                force_new_version=force_new_version,
                document_intelligence=document_intelligence_options,
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
    elif container.outbox_store is not None and not result.duplicate_version:
        from graph_rag.application.ingestion.enqueue import enqueue_ingest_ids

        run = await container.require_ingestion_repo().get_run(tenant, result.ingestion_run_id)
        await enqueue_ingest_ids(
            container.outbox_store,
            tenant=tenant,
            ingestion_run_id=result.ingestion_run_id,
            document_id=result.document_id,
            version_id=result.version_id,
            content_hash=(run.content_hash if run is not None else ""),
            config_fingerprint=(run.config_fingerprint if run is not None else ""),
            correlation_id=run.correlation_id if run is not None else None,
        )

    await container.commit_db()
    return IngestAcceptedResponse(
        ingestion_run_id=result.ingestion_run_id,
        document_id=result.document_id,
        version_id=result.version_id,
        duplicate_version=result.duplicate_version,
    )


def _document_response(
    document: DocumentRecord,
    *,
    page_count: int | None = None,
) -> DocumentResponse:
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
        page_count=page_count,
    )


async def _document_response_with_version(
    container: ServiceContainer,
    tenant: TenantContext,
    document: DocumentRecord,
) -> DocumentResponse:
    page_count: int | None = None
    meta_pages = document.metadata.get("page_count")
    if isinstance(meta_pages, int) and meta_pages > 0:
        page_count = meta_pages
    elif document.current_version_id is not None:
        version = await container.require_document_repo().get_version(
            tenant,
            document.current_version_id,
        )
        if version is not None and version.page_count:
            page_count = int(version.page_count)
    return _document_response(document, page_count=page_count)


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
        tenant, offset=0, limit=max(offset + limit, 200)
    )
    authz = container.require_authorization()
    allowed = filter_authorized_documents(authz, tenant, items)
    total = len(allowed)
    page = allowed[offset : offset + limit]
    return DocumentListResponse(
        items=[_document_response(item) for item in page],
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
    ensure_document_read(container.require_authorization(), tenant, document)
    return await _document_response_with_version(container, tenant, document)


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
    body: ReprocessRequest | None = None,
) -> ReprocessAcceptedResponse:
    """Re-index an already stored document without re-uploading the file."""
    try:
        reindex_scope = ReindexScope(scope.lower())
    except ValueError as exc:
        raise ValidationError(
            "scope must be one of: full, vectors, graph, document_intelligence",
            details={"scope": scope},
        ) from exc

    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    require_action(
        container.require_authorization(),
        tenant,
        Action.DOCUMENT_REINDEX,
        document=document,
    )
    result = await container.submit_reindex(
        tenant,
        document_id=document_id,
        scope=reindex_scope,
        document_intelligence=body.document_intelligence if body else None,
    )
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is not None:
        document.status = DocumentLifecycleStatus.INGESTING
        await container.require_document_repo().update_document(tenant, document)

    auto_run_scopes = {
        ReindexScope.FULL,
        ReindexScope.VECTORS,
        ReindexScope.DOCUMENT_INTELLIGENCE,
    }
    if (
        container.auto_process_ingest
        and result.ingestion_run_id is not None
        and reindex_scope in auto_run_scopes
    ):
        background_tasks.add_task(
            _run_local_ingest,
            container,
            tenant,
            result.ingestion_run_id,
        )
    elif (
        container.outbox_store is not None
        and result.ingestion_run_id is not None
        and reindex_scope in auto_run_scopes
    ):
        from graph_rag.application.ingestion.enqueue import enqueue_ingest_ids

        run = await container.require_ingestion_repo().get_run(tenant, result.ingestion_run_id)
        await enqueue_ingest_ids(
            container.outbox_store,
            tenant=tenant,
            ingestion_run_id=result.ingestion_run_id,
            document_id=result.document_id,
            version_id=result.version_id,
            content_hash=(run.content_hash if run is not None else ""),
            config_fingerprint=(run.config_fingerprint if run is not None else ""),
            correlation_id=run.correlation_id if run is not None else None,
        )

    await container.commit_db()
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


@router.get(
    "/{document_id}/ingestion-runs/latest",
    response_model=IngestionRunResponse,
)
async def get_latest_ingestion_run(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> IngestionRunResponse:
    """Most recent ingestion run for a document, for live progress polling."""
    from graph_rag.api.routes.ingestion import _run_response

    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    repo = container.require_ingestion_repo()
    run = await repo.get_latest_run_for_document(tenant, document_id)
    if run is None:
        raise NotFoundError(
            "No ingestion run found for document", details={"document_id": str(document_id)}
        )
    stages = await repo.list_stages(tenant, run.ingestion_run_id)
    return _run_response(run, stages)


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
    ensure_document_read(container.require_authorization(), tenant, document)
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


def _extraction_run_response(
    run: DocumentExtractionRunRecord,
    fields: list[DocumentExtractedFieldRecord],
) -> DocumentExtractionRunItem:
    return DocumentExtractionRunItem(
        run_id=run.run_id,
        status=run.status,
        model_key=run.model_key,
        provider=run.provider,
        created_at=run.created_at,
        updated_at=run.updated_at,
        error_code=run.error_code,
        error_message=run.error_message,
        fields=[
            ExtractedFieldItem(
                name=field.name,
                value=field.value,
                normalized_value=field.normalized_value,
                confidence=field.confidence,
                confidence_band=field.confidence_band,
                page=field.page,
                source_text=field.source_text,
                extraction_method=field.extraction_method,
                model_name=field.model_name,
            )
            for field in fields
        ],
    )


@router.get("/{document_id}/extractions", response_model=DocumentExtractionListResponse)
async def list_document_extractions(
    document_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
    version_id: UUID | None = None,
) -> DocumentExtractionListResponse:
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    ensure_document_read(container.require_authorization(), tenant, document)
    resolved_version = version_id or document.current_version_id
    if resolved_version is None:
        return DocumentExtractionListResponse(items=[])
    repo = container.require_document_extraction_repo()
    runs = await repo.list_runs_for_version(tenant, document_id, resolved_version)
    items = []
    for run in runs:
        fields = await repo.list_fields_for_run(tenant, run.run_id)
        items.append(_extraction_run_response(run, fields))
    return DocumentExtractionListResponse(items=items)


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


@router.get("/{document_id}/pages/{page}/render")
async def render_document_page(
    document_id: UUID,
    page: int,
    tenant: TenantDep,
    container: ContainerDep,
    version_id: UUID | None = None,
) -> Response:
    """Rasterize one page of the original document to PNG.

    Used by the "Parsed content" viewer to render a page image that JS can
    overlay clickable element bounding boxes on -- something an
    iframe-embedded native PDF viewer (used by /original) can't support.
    """
    if page < 1:
        raise ValidationError("page must be >= 1")
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    resolved_version = version_id or document.current_version_id
    if resolved_version is None:
        raise NotFoundError(
            "Document has no version to render",
            details={"document_id": str(document_id)},
        )
    version = await container.require_document_repo().get_version(tenant, resolved_version)
    if version is None or not version.original_object_key:
        raise NotFoundError(
            "Original object not found",
            details={"document_id": str(document_id), "version_id": str(resolved_version)},
        )
    if version.page_count is not None and page > version.page_count:
        raise NotFoundError(
            "Page out of range",
            details={
                "document_id": str(document_id),
                "page": page,
                "page_count": version.page_count,
            },
        )
    data = await container.require_object_store().get_bytes(
        tenant, object_key=version.original_object_key
    )
    try:
        png_bytes = await asyncio.to_thread(render_visual_png, data, page, None)
    except Exception as exc:  # pypdfium2 raises on corrupt/out-of-range pages
        raise NotFoundError(
            "Unable to render page",
            details={"document_id": str(document_id), "page": page},
        ) from exc
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/{document_id}/pages/{page}/layout", response_model=PageLayoutResponse)
async def get_page_layout(
    document_id: UUID,
    page: int,
    tenant: TenantDep,
    container: ContainerDep,
    version_id: UUID | None = None,
) -> PageLayoutResponse:
    """Element bounding boxes + text for one page, for the click-to-highlight overlay.

    Sourced from the cached "normalized" object-store artifact rather than
    the (dead, never-populated) /elements route -- see that route's own
    ElementView projection, which nothing in the codebase ever constructs.
    """
    if page < 1:
        raise ValidationError("page must be >= 1")
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    resolved_version = version_id or document.current_version_id
    if resolved_version is None:
        raise NotFoundError(
            "Document has no version",
            details={"document_id": str(document_id)},
        )
    key = artifact_key(tenant.tenant_id, document_id, resolved_version, "normalized")
    try:
        raw = await container.require_object_store().get_bytes(tenant, object_key=key)
    except NotFoundError as exc:
        raise NotFoundError(
            "Page layout not available yet",
            details={"document_id": str(document_id), "version_id": str(resolved_version)},
        ) from exc
    normalized = NormalizedDocument.model_validate(json.loads(raw.decode("utf-8")))
    if page > normalized.page_count:
        raise NotFoundError(
            "Page out of range",
            details={
                "document_id": str(document_id),
                "page": page,
                "page_count": normalized.page_count,
            },
        )
    items = [
        PageElementItem(
            element_id=element.element_id,
            element_type=str(element.element_type),
            page_start=element.page_start,
            page_end=element.page_end,
            bounding_box=_first_bbox_for_page(element, page),
            text=element.normalized_content or element.raw_content or "",
        )
        for element in normalized.elements
        if element.page_start <= page <= element.page_end
    ]
    return PageLayoutResponse(
        document_id=document_id,
        version_id=resolved_version,
        page=page,
        elements=items,
    )


def _first_bbox_for_page(element: ElementBase, page: int) -> PageBoundingBox | None:
    for bbox in element.bounding_boxes:
        if bbox.page_number == page:
            return PageBoundingBox(x0=bbox.x0, y0=bbox.y0, x1=bbox.x1, y1=bbox.y1)
    return None


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
    document = await container.require_document_repo().get_document(tenant, document_id)
    if document is None:
        raise NotFoundError("Document not found", details={"document_id": str(document_id)})
    require_action(
        container.require_authorization(),
        tenant,
        Action.DOCUMENT_DELETE,
        document=document,
    )
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
