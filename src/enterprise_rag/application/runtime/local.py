"""Build a local in-memory service container for tests and CLI dry-runs."""

from __future__ import annotations

from uuid import UUID

from enterprise_rag.application.deletion import DeleteDocumentService, ReindexDocumentService
from enterprise_rag.application.generation import GenerateAnswerService, QueryDocumentsService
from enterprise_rag.application.ingestion import RegisterSourceService
from enterprise_rag.application.retrieval import RetrieveEvidenceService
from enterprise_rag.application.runtime.container import ServiceContainer
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.cache import InMemoryCacheInvalidator
from enterprise_rag.infrastructure.intake.source_loader import DefaultSourceLoader
from enterprise_rag.infrastructure.models import FakeChatModel, FakeEmbeddingModel
from enterprise_rag.infrastructure.observability import InMemoryAuditStore
from enterprise_rag.infrastructure.persistence.chunks import (
    InMemoryChunkLookupStore,
    InMemoryLexicalSearchStore,
)
from enterprise_rag.infrastructure.persistence.memory import (
    InMemoryDocumentRepository,
    InMemoryIngestionRepository,
    InMemoryObjectStore,
    InMemoryTenantRepository,
)
from enterprise_rag.infrastructure.persistence.neo4j import InMemoryGraphStore
from enterprise_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore
from enterprise_rag.infrastructure.security import NoOpMalwareScanner


def build_local_container(*, max_upload_bytes: int = 50_000_000) -> ServiceContainer:
    """Wire in-memory adapters suitable for unit tests and offline CLI."""
    tenant_repo = InMemoryTenantRepository()
    document_repo = InMemoryDocumentRepository()
    ingestion_repo = InMemoryIngestionRepository()
    object_store = InMemoryObjectStore()
    source_loader = DefaultSourceLoader(
        max_upload_bytes=max_upload_bytes,
        malware_scanner=NoOpMalwareScanner(),
    )
    register = RegisterSourceService(
        tenant_repo=tenant_repo,
        document_repo=document_repo,
        ingestion_repo=ingestion_repo,
        object_store=object_store,
        source_loader=source_loader,
    )
    embedder = FakeEmbeddingModel()
    vectors = InMemoryChunkVectorStore()
    chunks = InMemoryChunkLookupStore()
    lexical = InMemoryLexicalSearchStore()
    graph = InMemoryGraphStore()
    retrieve = RetrieveEvidenceService(
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=chunks,
        graph_store=graph,
        lexical_store=lexical,
    )
    query = QueryDocumentsService(
        retrieve,
        GenerateAnswerService(
            FakeChatModel(
                text='{"answer":"No indexed evidence yet.","citation_ids":[]}'
            )
        ),
    )

    def chunk_ids_for_version(
        tenant: TenantContext,
        document_id: UUID,
        version_id: UUID,
    ) -> list[UUID]:
        return [
            chunk.chunk_id
            for chunk in chunks.list_for_version(
                tenant,
                document_id=document_id,
                version_id=version_id,
            )
        ]

    delete_service = DeleteDocumentService(
        document_repo=document_repo,
        object_store=object_store,
        vector_store=vectors,
        graph_store=graph,
        cache=InMemoryCacheInvalidator(),
        chunk_id_provider=chunk_ids_for_version,
    )
    reindex_service = ReindexDocumentService(
        document_repo=document_repo,
        ingestion_repo=ingestion_repo,
        vector_store=vectors,
        graph_store=graph,
    )
    return ServiceContainer(
        tenant_repo=tenant_repo,
        document_repo=document_repo,
        ingestion_repo=ingestion_repo,
        object_store=object_store,
        register_source=register,
        retrieve=retrieve,
        query=query,
        graph_store=graph,
        vector_store=vectors,
        delete_document=delete_service,
        reindex_document=reindex_service,
        audit_store=InMemoryAuditStore(),
        ready_checks=[lambda: True],
    )
