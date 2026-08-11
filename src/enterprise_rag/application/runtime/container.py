"""Runtime service container shared by API and CLI."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from enterprise_rag.application.deletion import (
    DeleteDocumentService,
    DeletionResult,
    ReindexDocumentService,
    ReindexResult,
)
from enterprise_rag.application.generation.query import QueryDocumentsService
from enterprise_rag.application.ingestion.register_source import RegisterSourceService
from enterprise_rag.application.retrieval.retrieve import RetrieveEvidenceService
from enterprise_rag.domain.chunks.protocols import ChunkVectorStore
from enterprise_rag.domain.deletion.stages import (
    DeletionOperationStatus,
    ReindexScope,
)
from enterprise_rag.domain.graph.protocols import GraphStore
from enterprise_rag.domain.ids import deterministic_id, new_id
from enterprise_rag.domain.ingestion.protocols import (
    DocumentRepository,
    IngestionRepository,
    TenantRepository,
)
from enterprise_rag.domain.ingestion.stages import DocumentLifecycleStatus, IngestionRunStatus
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.storage.protocols import ObjectStore
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import ConfigurationError, NotFoundError, ValidationError

ReadyCheck = Callable[[], Awaitable[bool] | bool]


@dataclass
class ElementView:
    """Lightweight element projection for API listing."""

    element_id: UUID
    document_id: UUID
    version_id: UUID
    element_type: str
    modality: Modality
    page_start: int
    page_end: int
    section_path: list[str] = field(default_factory=list)
    preview: str = ""


@dataclass
class DeletionOperation:
    """Async deletion operation handle."""

    operation_id: UUID
    tenant_id: UUID
    document_id: UUID
    status: str = "accepted"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    result: DeletionResult | None = None


@dataclass
class ServiceContainer:
    """Injectable dependencies for HTTP and CLI entrypoints."""

    tenant_repo: TenantRepository | None = None
    document_repo: DocumentRepository | None = None
    ingestion_repo: IngestionRepository | None = None
    object_store: ObjectStore | None = None
    register_source: RegisterSourceService | None = None
    retrieve: RetrieveEvidenceService | None = None
    query: QueryDocumentsService | None = None
    graph_store: GraphStore | None = None
    vector_store: ChunkVectorStore | None = None
    chunk_store: Any | None = None
    delete_document: DeleteDocumentService | None = None
    reindex_document: ReindexDocumentService | None = None
    audit_store: Any | None = None
    parsing_audit_repo: Any | None = None
    process_ingestion: Any | None = None
    auto_process_ingest: bool = False
    elements: dict[tuple[UUID, UUID], list[ElementView]] = field(default_factory=dict)
    deletions: dict[UUID, DeletionOperation] = field(default_factory=dict)
    assets: dict[tuple[UUID, UUID], str] = field(default_factory=dict)
    ready_checks: list[ReadyCheck] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=lambda: {"requests_total": 0})
    db_session: Any | None = None
    on_commit: Any | None = None
    user_repo: Any | None = None
    auth_service: Any | None = None

    async def commit_db(self) -> None:
        """Commit the metadata DB session when Postgres is wired."""
        if callable(self.on_commit):
            maybe = self.on_commit()
            if hasattr(maybe, "__await__"):
                await maybe
            return
        session = self.db_session
        if session is not None:
            await session.commit()

    def require_register_source(self) -> RegisterSourceService:
        if self.register_source is None:
            raise ConfigurationError("Register source service is not configured")
        return self.register_source

    def require_document_repo(self) -> DocumentRepository:
        if self.document_repo is None:
            raise ConfigurationError("Document repository is not configured")
        return self.document_repo

    def require_ingestion_repo(self) -> IngestionRepository:
        if self.ingestion_repo is None:
            raise ConfigurationError("Ingestion repository is not configured")
        return self.ingestion_repo

    def require_parsing_audit_repo(self) -> Any:
        if self.parsing_audit_repo is None:
            raise ConfigurationError("Parsing audit repository is not configured")
        return self.parsing_audit_repo

    def require_retrieve(self) -> RetrieveEvidenceService:
        if self.retrieve is None:
            raise ConfigurationError("Retrieval service is not configured")
        return self.retrieve

    def require_query(self) -> QueryDocumentsService:
        if self.query is None:
            raise ConfigurationError("Query service is not configured")
        return self.query

    def require_object_store(self) -> ObjectStore:
        if self.object_store is None:
            raise ConfigurationError("Object store is not configured")
        return self.object_store

    def require_process_ingestion(self) -> Any:
        if self.process_ingestion is None:
            raise ConfigurationError("Ingestion processor is not configured")
        return self.process_ingestion

    async def resolve_tenant(
        self,
        *,
        tenant_id: UUID | None = None,
        tenant_key: str | None = None,
        principal: str | None = None,
    ) -> TenantContext:
        if tenant_id is not None:
            context = TenantContext(
                tenant_id=tenant_id,
                tenant_key=tenant_key,
                principal=principal,
            )
            return context.ensure_authorized()
        if tenant_key:
            resolved_id: UUID | None = None
            if self.tenant_repo is not None:
                record = await self.tenant_repo.get_by_key(tenant_key)
                if record is not None:
                    resolved_id = record.tenant_id
            if resolved_id is None:
                resolved_id = deterministic_id("tenant", tenant_key)
            return TenantContext(
                tenant_id=resolved_id,
                tenant_key=tenant_key,
                principal=principal,
            ).ensure_authorized()
        raise ValidationError("Provide X-Tenant-ID or X-Tenant-Key / --tenant-id")

    async def list_elements(
        self,
        tenant: TenantContext,
        document_id: UUID,
        *,
        version_id: UUID | None = None,
        page: int | None = None,
        modality: Modality | None = None,
        element_type: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ElementView], int]:
        items = list(self.elements.get((tenant.tenant_id, document_id), []))
        if version_id is not None:
            items = [item for item in items if item.version_id == version_id]
        if page is not None:
            items = [item for item in items if item.page_start <= page <= item.page_end]
        if modality is not None:
            items = [item for item in items if item.modality is modality]
        if element_type is not None:
            items = [item for item in items if item.element_type == element_type]
        total = len(items)
        return items[offset : offset + limit], total

    async def list_chunks(
        self,
        tenant: TenantContext,
        document_id: UUID,
        *,
        version_id: UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Any], int]:
        """List indexed chunks for a document (for UI preview)."""
        document = await self.require_document_repo().get_document(tenant, document_id)
        if document is None:
            raise NotFoundError(
                "Document not found",
                details={"document_id": str(document_id)},
            )
        resolved_version = version_id or document.current_version_id
        if resolved_version is None or self.chunk_store is None:
            return [], 0
        list_fn = getattr(self.chunk_store, "list_for_version", None)
        if list_fn is None:
            return [], 0
        items = list(
            list_fn(
                tenant,
                document_id=document_id,
                version_id=resolved_version,
            )
        )
        items.sort(key=lambda chunk: (chunk.page_start, chunk.page_end, str(chunk.chunk_id)))
        total = len(items)
        return items[offset : offset + limit], total

    async def submit_deletion(
        self,
        tenant: TenantContext,
        document_id: UUID,
        *,
        execute_now: bool = True,
    ) -> DeletionOperation:
        operation = DeletionOperation(
            operation_id=new_id(),
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            status=DeletionOperationStatus.ACCEPTED.value,
        )
        self.deletions[operation.operation_id] = operation
        if not execute_now:
            repo = self.require_document_repo()
            document = await repo.get_document(tenant, document_id)
            if document is None:
                raise NotFoundError(
                    "Document not found",
                    details={"document_id": str(document_id)},
                )
            document.status = DocumentLifecycleStatus.DELETING
            await repo.update_document(tenant, document)
            return operation

        service = self.delete_document
        if service is None:
            # Fallback soft-delete when full cleanup service is absent.
            repo = self.require_document_repo()
            document = await repo.get_document(tenant, document_id)
            if document is None:
                raise NotFoundError(
                    "Document not found",
                    details={"document_id": str(document_id)},
                )
            document.status = DocumentLifecycleStatus.DELETED
            await repo.update_document(tenant, document)
            operation.status = DeletionOperationStatus.COMPLETED.value
            return operation

        result = await service.execute(
            tenant,
            document_id=document_id,
            operation_id=operation.operation_id,
        )
        operation.status = result.status.value
        operation.result = result
        self.elements.pop((tenant.tenant_id, document_id), None)
        return operation

    async def submit_reindex(
        self,
        tenant: TenantContext,
        document_id: UUID,
        *,
        scope: ReindexScope = ReindexScope.FULL,
    ) -> ReindexResult:
        if self.reindex_document is None:
            raise ConfigurationError("Reindex service is not configured")
        return await self.reindex_document.execute(
            tenant,
            document_id=document_id,
            scope=scope,
        )

    async def resume_run(self, tenant: TenantContext, run_id: UUID) -> Any:
        repo = self.require_ingestion_repo()
        run = await repo.get_run(tenant, run_id)
        if run is None:
            raise NotFoundError("Ingestion run not found", details={"run_id": str(run_id)})
        if run.status not in {
            IngestionRunStatus.FAILED,
            IngestionRunStatus.PARTIAL,
            IngestionRunStatus.PENDING,
        }:
            raise ValidationError(
                "Run is not eligible for resume",
                details={"status": run.status.value},
            )
        run.status = IngestionRunStatus.PENDING
        run.error_code = None
        run.error_message = None
        return await repo.update_run(tenant, run)

    async def cancel_run(self, tenant: TenantContext, run_id: UUID) -> Any:
        repo = self.require_ingestion_repo()
        run = await repo.get_run(tenant, run_id)
        if run is None:
            raise NotFoundError("Ingestion run not found", details={"run_id": str(run_id)})
        if run.status in {
            IngestionRunStatus.COMPLETED,
            IngestionRunStatus.COMPLETED_WITH_WARNINGS,
            IngestionRunStatus.CANCELLED,
        }:
            raise ValidationError(
                "Run cannot be cancelled in its current state",
                details={"status": run.status.value},
            )
        run.status = IngestionRunStatus.CANCELLED
        return await repo.update_run(tenant, run)
