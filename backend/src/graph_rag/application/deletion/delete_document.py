"""Staged document deletion with derived-index cleanup."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from inspect import isawaitable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.chunks.protocols import ChunkVectorStore
from graph_rag.domain.deletion.protocols import CacheInvalidator
from graph_rag.domain.deletion.stages import (
    DeletionOperationStatus,
    DeletionStageName,
)
from graph_rag.domain.graph.protocols import GraphStore
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.protocols import DocumentRepository, IngestionRepository
from graph_rag.domain.ingestion.stages import (
    TERMINAL_RUN_STATUSES,
    DocumentLifecycleStatus,
    IngestionRunStatus,
)
from graph_rag.domain.retrieval.protocols import ChunkLookupStore, LexicalSearchStore
from graph_rag.domain.storage.protocols import ObjectStore, version_prefix
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import NotFoundError, ValidationError
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)

type ChunkIdProvider = Callable[
    [TenantContext, UUID, UUID],
    Sequence[UUID] | Awaitable[Sequence[UUID]],
]


class DeletionResult(BaseModel):
    """Outcome of a completed (or partial) deletion use case."""

    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID | None = None
    status: DeletionOperationStatus
    stages_completed: list[DeletionStageName] = Field(default_factory=list)
    vectors_deleted: int = 0
    graph_deleted: int = 0
    objects_deleted: int = 0
    cache_keys_invalidated: int = 0
    warnings: list[str] = Field(default_factory=list)
    error_message: str | None = None
    completed_at: datetime | None = None


@dataclass
class DeleteDocumentService:
    """Remove derived indexes, version assets and archive Postgres state."""

    document_repo: DocumentRepository
    object_store: ObjectStore | None = None
    vector_store: ChunkVectorStore | None = None
    graph_store: GraphStore | None = None
    chunk_store: ChunkLookupStore | None = None
    lexical_store: LexicalSearchStore | None = None
    cache: CacheInvalidator | None = None
    chunk_id_provider: ChunkIdProvider | None = None
    ingestion_repo: IngestionRepository | None = None

    async def execute(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        operation_id: UUID | None = None,
        retain_postgres: bool = False,
        delete_vectors: bool = True,
        delete_graph: bool = True,
        delete_objects: bool = True,
    ) -> DeletionResult:
        tenant.ensure_authorized()
        document = await self.document_repo.get_document(tenant, document_id)
        if document is None:
            raise NotFoundError(
                "Document not found",
                details={"document_id": str(document_id)},
            )
        if document.status is DocumentLifecycleStatus.DELETED:
            raise ValidationError(
                "Document is already deleted",
                details={"document_id": str(document_id)},
            )

        op_id = operation_id or new_id()
        stages: list[DeletionStageName] = []
        warnings: list[str] = []
        vectors_deleted = 0
        graph_deleted = 0
        objects_deleted = 0
        cache_keys = 0
        version_id = document.current_version_id

        # A still-running ingestion run left alive after deletion will keep
        # retrying against a document whose original file this deletion is
        # about to purge -- its eventual failure would otherwise flip
        # document.status back from DELETED to FAILED, resurrecting a
        # deleted document in every list/detail view.
        if self.ingestion_repo is not None:
            active_run = await self.ingestion_repo.get_latest_run_for_document(tenant, document_id)
            if active_run is not None and active_run.status not in TERMINAL_RUN_STATUSES:
                active_run.status = IngestionRunStatus.CANCELLED
                active_run.error_code = "cancelled"
                active_run.error_message = "Run cancelled: document was deleted."
                await self.ingestion_repo.update_run(tenant, active_run)

        document.status = DocumentLifecycleStatus.DELETING
        await self.document_repo.update_document(tenant, document)
        stages.append(DeletionStageName.MARK_DELETING)

        chunk_ids = await self._resolve_chunk_ids(tenant, document_id, version_id)

        if not delete_vectors:
            warnings.append("vectors_retained")
        elif self.vector_store is not None:
            # Prefer full-document purge so prior versions cannot orphan vectors.
            delete_document = getattr(self.vector_store, "delete_document", None)
            if callable(delete_document):
                vectors_deleted = await delete_document(
                    tenant,
                    document_id=document_id,
                )
            elif version_id is not None:
                vectors_deleted = await self.vector_store.delete_version(
                    tenant,
                    document_id=document_id,
                    version_id=version_id,
                )
            stages.append(DeletionStageName.DELETE_VECTORS)
        else:
            warnings.append("vector_store_not_configured")

        if version_id is not None and self.chunk_store is not None:
            await self.chunk_store.delete_version(
                tenant,
                document_id=document_id,
                version_id=version_id,
            )
        if version_id is not None and self.lexical_store is not None:
            await self.lexical_store.delete_version(
                tenant,
                document_id=document_id,
                version_id=version_id,
            )

        if not delete_graph:
            warnings.append("graph_retained")
        elif version_id is not None and self.graph_store is not None:
            graph_deleted = await self.graph_store.delete_version(
                tenant,
                document_id=document_id,
                version_id=version_id,
                chunk_ids=chunk_ids or None,
            )
            stages.append(DeletionStageName.DELETE_GRAPH)
        elif self.graph_store is None:
            warnings.append("graph_store_not_configured")

        if not delete_objects:
            warnings.append("objects_retained")
        elif version_id is not None and self.object_store is not None:
            prefix = version_prefix(
                tenant_id=tenant.tenant_id,
                document_id=document_id,
                version_id=version_id,
            )
            objects_deleted = await self.object_store.delete_prefix(tenant, prefix=prefix)
            stages.append(DeletionStageName.DELETE_OBJECTS)
        elif self.object_store is None:
            warnings.append("object_store_not_configured")

        if not retain_postgres:
            if version_id is not None:
                version = await self.document_repo.get_version(tenant, version_id)
                if version is not None:
                    version.status = DocumentLifecycleStatus.DELETED
                    # Versions are immutable in protocol — update via create not available;
                    # status flip requires repository update; use document metadata archive.
                    document.metadata = {
                        **document.metadata,
                        "deleted_version_id": str(version_id),
                        "deleted_at": datetime.now(UTC).isoformat(),
                    }
            document.status = DocumentLifecycleStatus.DELETED
            document.current_version_id = None
            await self.document_repo.update_document(tenant, document)
            stages.append(DeletionStageName.ARCHIVE_POSTGRES)
        else:
            warnings.append("postgres_retained")

        if self.cache is not None:
            cache_keys = await self.cache.invalidate_document(
                tenant,
                document_id=document_id,
                version_id=version_id,
            )
            stages.append(DeletionStageName.INVALIDATE_CACHE)

        stages.append(DeletionStageName.FINALIZE)
        status = DeletionOperationStatus.PARTIAL if warnings else DeletionOperationStatus.COMPLETED
        result = DeletionResult(
            operation_id=op_id,
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            status=status,
            stages_completed=stages,
            vectors_deleted=vectors_deleted,
            graph_deleted=graph_deleted,
            objects_deleted=objects_deleted,
            cache_keys_invalidated=cache_keys,
            warnings=warnings,
            completed_at=datetime.now(UTC),
        )
        logger.info(
            "document_deleted",
            document_id=str(document_id),
            version_id=str(version_id) if version_id else None,
            status=status.value,
            vectors_deleted=vectors_deleted,
            graph_deleted=graph_deleted,
            objects_deleted=objects_deleted,
        )
        return result

    async def _resolve_chunk_ids(
        self,
        tenant: TenantContext,
        document_id: UUID,
        version_id: UUID | None,
    ) -> list[UUID]:
        provider = self.chunk_id_provider
        if provider is None or version_id is None:
            return []
        result = provider(tenant, document_id, version_id)
        if isawaitable(result):
            result = await result
        return list(result)
