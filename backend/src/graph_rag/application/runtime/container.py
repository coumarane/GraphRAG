"""Runtime service container shared by API and CLI."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from graph_rag.application.deletion import (
    DeleteDocumentService,
    DeletionResult,
    ReindexDocumentService,
    ReindexResult,
)
from graph_rag.application.document_intelligence.models import DocumentIntelligenceIngestOptions
from graph_rag.application.generation.query import QueryDocumentsService
from graph_rag.application.ingestion.register_source import RegisterSourceService
from graph_rag.application.retrieval.retrieve import RetrieveEvidenceService
from graph_rag.domain.chunks.protocols import ChunkVectorStore
from graph_rag.domain.conversation.protocols import (
    ChatConversationRepository,
    ChatProjectRepository,
)
from graph_rag.domain.deletion.stages import (
    DeletionOperationStatus,
    ReindexScope,
)
from graph_rag.domain.document_intelligence.protocols import (
    DocumentExtractionRepository,
    DocumentIntelligenceModelRepository,
)
from graph_rag.domain.graph.protocols import GraphStore
from graph_rag.domain.ids import deterministic_id, new_id
from graph_rag.domain.ingestion.protocols import (
    DocumentRepository,
    IngestionRepository,
    TenantRepository,
)
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus, IngestionRunStatus
from graph_rag.domain.modality import Modality
from graph_rag.domain.storage.protocols import ObjectStore
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import ConfigurationError, NotFoundError, ValidationError

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
    chat_project_repo: ChatProjectRepository | None = None
    chat_conversation_repo: ChatConversationRepository | None = None
    document_intelligence_model_repo: DocumentIntelligenceModelRepository | None = None
    document_extraction_repo: DocumentExtractionRepository | None = None
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
    usage_repo: Any | None = None
    process_ingestion: Any | None = None
    auto_process_ingest: bool = False
    ingest_queue: Any | None = None
    outbox_store: Any | None = None
    dead_letter_store: Any | None = None
    outbox_publisher: Any | None = None
    elements: dict[tuple[UUID, UUID], list[ElementView]] = field(default_factory=dict)
    deletions: dict[UUID, DeletionOperation] = field(default_factory=dict)
    assets: dict[tuple[UUID, UUID], str] = field(default_factory=dict)
    ready_checks: list[ReadyCheck] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=lambda: {"requests_total": 0})
    db_session: Any | None = None
    on_commit: Any | None = None
    user_repo: Any | None = None
    auth_service: Any | None = None
    authorization: Any | None = None
    quotas: Any | None = None
    parser_registry: Any | None = None

    def require_authorization(self) -> Any:
        if self.authorization is None:
            from graph_rag.application.authorization.service import (
                PolicyAuthorizationService,
            )

            self.authorization = PolicyAuthorizationService()
        return self.authorization

    def require_quotas(self) -> Any:
        if self.quotas is None:
            from graph_rag.application.quotas.service import InMemoryQuotaService

            self.quotas = InMemoryQuotaService()
            self.quotas.ensure_default_plan()
        return self.quotas

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

    async def rollback_db(self) -> None:
        """Clear a failed transaction so the shared session can continue."""
        session = self.db_session
        if session is None:
            return
        try:
            await session.rollback()
        except Exception:
            pass

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

    def require_chat_project_repo(self) -> ChatProjectRepository:
        if self.chat_project_repo is None:
            raise ConfigurationError("Chat project repository is not configured")
        return self.chat_project_repo

    def require_chat_conversation_repo(self) -> ChatConversationRepository:
        if self.chat_conversation_repo is None:
            raise ConfigurationError("Chat conversation repository is not configured")
        return self.chat_conversation_repo

    def require_document_intelligence_model_repo(self) -> DocumentIntelligenceModelRepository:
        if self.document_intelligence_model_repo is None:
            raise ConfigurationError("Document Intelligence model repository is not configured")
        return self.document_intelligence_model_repo

    def require_document_extraction_repo(self) -> DocumentExtractionRepository:
        if self.document_extraction_repo is None:
            raise ConfigurationError("Document extraction repository is not configured")
        return self.document_extraction_repo

    def require_parsing_audit_repo(self) -> Any:
        if self.parsing_audit_repo is None:
            raise ConfigurationError("Parsing audit repository is not configured")
        return self.parsing_audit_repo

    def require_usage_repo(self) -> Any:
        if self.usage_repo is None:
            raise ConfigurationError("Usage repository is not configured")
        return self.usage_repo

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
        document_intelligence: DocumentIntelligenceIngestOptions | None = None,
    ) -> ReindexResult:
        if self.reindex_document is None:
            raise ConfigurationError("Reindex service is not configured")
        return await self.reindex_document.execute(
            tenant,
            document_id=document_id,
            scope=scope,
            document_intelligence=document_intelligence,
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
        run.error_code = "cancelled"
        run.error_message = "Run cancelled by user."
        updated_run = await repo.update_run(tenant, run)
        # A cancelled run otherwise leaves the document's own status
        # (set to INGESTING when the run started) permanently stuck --
        # nothing else ever revisits it, so the document list would show
        # "ingesting" forever with no run left to finish or retry it.
        document_repo = self.require_document_repo()
        document = await document_repo.get_document(tenant, run.document_id)
        if document is not None and document.status == DocumentLifecycleStatus.INGESTING:
            document.status = DocumentLifecycleStatus.FAILED
            document.updated_at = datetime.now(UTC)
            await document_repo.update_document(tenant, document)
        return updated_run
