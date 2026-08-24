"""Build a local in-memory service container for tests and CLI dry-runs."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from graph_rag.application.deletion import DeleteDocumentService, ReindexDocumentService
from graph_rag.application.document_intelligence.providers.internal import (
    InternalExtractionProvider,
)
from graph_rag.application.generation import GenerateAnswerService, QueryDocumentsService
from graph_rag.application.ingestion import RegisterSourceService
from graph_rag.application.ingestion.local_pipeline import ProcessRegisteredDocumentService
from graph_rag.application.retrieval import RetrieveEvidenceService
from graph_rag.application.runtime.container import ServiceContainer
from graph_rag.domain.chunks.protocols import ChunkVectorStore
from graph_rag.domain.conversation.protocols import (
    ChatConversationRepository,
    ChatProjectRepository,
)
from graph_rag.domain.document_intelligence.protocols import (
    DocumentExtractionRepository,
    DocumentIntelligenceModelRepository,
)
from graph_rag.domain.graph.protocols import GraphStore
from graph_rag.domain.ingestion.protocols import (
    DocumentRepository,
    IngestionRepository,
    TenantRepository,
)
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus
from graph_rag.domain.models.protocols import ChatModel, EmbeddingModel, StructuredExtractor
from graph_rag.domain.parsing.audit_protocols import ParsingAuditRepository
from graph_rag.domain.storage.protocols import ObjectStore
from graph_rag.domain.tenant import TenantContext
from graph_rag.domain.usage.protocols import UsageRepository
from graph_rag.infrastructure.cache import InMemoryCacheInvalidator
from graph_rag.infrastructure.intake.source_loader import DefaultSourceLoader
from graph_rag.infrastructure.models import (
    FakeChatModel,
    FakeEmbeddingModel,
    HeuristicReranker,
)
from graph_rag.infrastructure.observability import InMemoryAuditStore
from graph_rag.infrastructure.persistence.chunks import (
    InMemoryChunkLookupStore,
    InMemoryLexicalSearchStore,
    QdrantChunkLookupStore,
)
from graph_rag.infrastructure.persistence.chunks.lexical_qdrant import (
    QdrantHydratingLexicalStore,
)
from graph_rag.infrastructure.persistence.memory import (
    InMemoryChatConversationRepository,
    InMemoryChatProjectRepository,
    InMemoryDocumentExtractionRepository,
    InMemoryDocumentIntelligenceModelRepository,
    InMemoryDocumentRepository,
    InMemoryIngestionRepository,
    InMemoryObjectStore,
    InMemoryTenantRepository,
    InMemoryUsageRepository,
)
from graph_rag.infrastructure.persistence.memory.parsing_audit import (
    InMemoryParsingAuditRepository,
)
from graph_rag.infrastructure.persistence.neo4j import InMemoryGraphStore
from graph_rag.infrastructure.persistence.qdrant import (
    InMemoryChunkVectorStore,
    QdrantChunkVectorStore,
)
from graph_rag.infrastructure.security import NoOpMalwareScanner


def _resolve_models(
    *,
    embedding_model: EmbeddingModel | None,
    chat_model: ChatModel | None,
    usage_recorder: Any | None = None,
) -> tuple[EmbeddingModel, ChatModel]:
    if embedding_model is not None and chat_model is not None:
        return embedding_model, chat_model

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    embed_name = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    answer_name = os.environ.get("OPENAI_ANSWER_MODEL", "gpt-4o-mini")
    if not api_key:
        try:
            from graph_rag.config.settings import get_settings

            settings = get_settings()
            if settings.models.api_key is not None:
                api_key = settings.models.api_key.get_secret_value().strip()
            embed_name = settings.models.embedding_model or embed_name
            answer_name = settings.models.answer_model or answer_name
        except Exception:
            api_key = ""

    if api_key and embedding_model is None and chat_model is None:
        from graph_rag.infrastructure.models.openai_direct import (
            OpenAIChatModel,
            OpenAIEmbeddingModel,
        )

        return (
            OpenAIEmbeddingModel(
                model_name=embed_name,
                api_key=api_key,
                usage_recorder=usage_recorder,
            ),
            OpenAIChatModel(
                model_name=answer_name,
                api_key=api_key,
                usage_recorder=usage_recorder,
            ),
        )

    def _fake_grounded(request: object) -> str:
        import json
        import re

        messages = getattr(request, "messages", None) or []
        user = ""
        for message in messages:
            if getattr(message, "role", None) and str(message.role).endswith("user"):
                user = getattr(message, "content", "") or ""
        ids = re.findall(r"\[(C\d+)\]", user)
        # Prefer explicit evidence blocks labeled [C1] ...
        blocks = re.findall(
            r"\[(C\d+)\][^\n]*\n([\s\S]*?)(?=\n\[C\d+\]|\Z)",
            user,
        )
        if blocks:
            citation_id, text = blocks[0]
            snippet = " ".join(text.split())[:500]
            answer = f"{snippet} [{citation_id}]"
            return json.dumps({"answer": answer, "citation_ids": [citation_id]})
        if ids:
            return json.dumps(
                {
                    "answer": "See cited evidence. [" + ids[0] + "]",
                    "citation_ids": [ids[0]],
                }
            )
        return json.dumps(
            {
                "answer": "I could not find enough retrieved evidence to answer.",
                "citation_ids": [],
            }
        )

    return (
        embedding_model or FakeEmbeddingModel(),
        chat_model or FakeChatModel(response_fn=_fake_grounded),
    )


def _parse_service_from_registry(parser_registry: Any | None) -> Any | None:
    if parser_registry is None:
        return None
    from graph_rag.infrastructure.parsers.registry import ParseDocumentService

    inspector_name = getattr(parser_registry, "inspector_name", None)
    return ParseDocumentService(registry=parser_registry, inspector_name=inspector_name)


def build_local_container(
    *,
    max_upload_bytes: int = 50_000_000,
    object_store: ObjectStore | None = None,
    embedding_model: EmbeddingModel | None = None,
    chat_model: ChatModel | None = None,
    vector_store: ChunkVectorStore | None = None,
    graph_store: GraphStore | None = None,
    tenant_repo: TenantRepository | None = None,
    document_repo: DocumentRepository | None = None,
    ingestion_repo: IngestionRepository | None = None,
    chat_project_repo: ChatProjectRepository | None = None,
    chat_conversation_repo: ChatConversationRepository | None = None,
    document_intelligence_model_repo: DocumentIntelligenceModelRepository | None = None,
    document_intelligence_provider: InternalExtractionProvider | None = None,
    document_extraction_repo: DocumentExtractionRepository | None = None,
    parsing_audit_repo: ParsingAuditRepository | None = None,
    usage_repo: UsageRepository | None = None,
    structured_extractor: StructuredExtractor | None = None,
    auto_process_ingest: bool = False,
    use_live_models: bool = False,
    max_pages: int = 2_000,
    on_commit: Callable[[], Awaitable[None]] | None = None,
    enable_semantic_graph: bool = True,
    parser_registry: Any | None = None,
) -> ServiceContainer:
    """Wire adapters for tests, CLI, and local/dev API.

    Defaults keep repositories and indexes in-memory. Pass MinIO / Qdrant / Neo4j
    / Postgres adapters for a fuller local stack.
    """
    tenant_repo = tenant_repo or InMemoryTenantRepository()
    document_repo = document_repo or InMemoryDocumentRepository()
    ingestion_repo = ingestion_repo or InMemoryIngestionRepository()
    chat_conversation_repo = chat_conversation_repo or InMemoryChatConversationRepository()
    if chat_project_repo is None:
        # Link the two in-memory stores so deleting a project can un-file its
        # conversations itself (the Postgres repo gets this for free from the
        # real ON DELETE SET NULL foreign key).
        chat_project_repo = InMemoryChatProjectRepository(
            chat_conversation_repo
            if isinstance(chat_conversation_repo, InMemoryChatConversationRepository)
            else None
        )
    document_intelligence_model_repo = (
        document_intelligence_model_repo or InMemoryDocumentIntelligenceModelRepository()
    )
    document_extraction_repo = document_extraction_repo or InMemoryDocumentExtractionRepository()
    parsing_audit_repo = parsing_audit_repo or InMemoryParsingAuditRepository()
    usage_repo = usage_repo or InMemoryUsageRepository()
    object_store = object_store if object_store is not None else InMemoryObjectStore()
    source_loader = DefaultSourceLoader(
        max_upload_bytes=max_upload_bytes,
        malware_scanner=NoOpMalwareScanner(),
    )
    from graph_rag.application.authorization.filters import filter_authorized_documents
    from graph_rag.application.authorization.service import PolicyAuthorizationService
    from graph_rag.application.quotas.service import InMemoryQuotaService

    authorization = PolicyAuthorizationService()
    quotas = InMemoryQuotaService()
    quotas.ensure_default_plan()
    register = RegisterSourceService(
        tenant_repo=tenant_repo,
        document_repo=document_repo,
        ingestion_repo=ingestion_repo,
        object_store=object_store,
        source_loader=source_loader,
        authorization=authorization,
        quotas=quotas,
    )
    if use_live_models:
        embedder, chat = _resolve_models(
            embedding_model=embedding_model,
            chat_model=chat_model,
            usage_recorder=usage_repo,
        )
    else:
        embedder = embedding_model or FakeEmbeddingModel()
        chat = chat_model or FakeChatModel(
            text='{"answer":"No indexed evidence yet.","citation_ids":[]}'
        )
    vision_max_pages_value = int(os.environ.get("VISION_MAX_PAGES", "0") or "0")
    if document_intelligence_provider is None:
        from graph_rag.config.settings import get_settings as _get_settings

        di_settings = _get_settings().document_intelligence
        document_intelligence_provider = InternalExtractionProvider(
            embedding_model=embedder,
            chat_model=chat,
            enable_llm_tier=di_settings.enable_llm_tier,
            enable_vision_tier=di_settings.enable_vision_tier,
            vision_max_pages=vision_max_pages_value,
        )
    extractor = structured_extractor
    if extractor is None and use_live_models:
        from graph_rag.infrastructure.models.openai_direct import ChatStructuredExtractor

        extractor = ChatStructuredExtractor(chat)
    vectors = vector_store if vector_store is not None else InMemoryChunkVectorStore()
    if isinstance(vectors, QdrantChunkVectorStore):
        chunks = QdrantChunkLookupStore(settings=getattr(vectors, "_settings", None))
        lexical = QdrantHydratingLexicalStore(chunks)
    else:
        chunks = InMemoryChunkLookupStore()
        lexical = InMemoryLexicalSearchStore()
    graph = graph_store if graph_store is not None else InMemoryGraphStore()

    async def active_document_ids(tenant: TenantContext) -> list[UUID]:
        items, _total = await document_repo.list_documents(tenant, offset=0, limit=500)
        ready = [
            item
            for item in items
            if item.status in {DocumentLifecycleStatus.READY, DocumentLifecycleStatus.PARTIAL}
        ]
        return [
            item.document_id for item in filter_authorized_documents(authorization, tenant, ready)
        ]

    async def document_titles(tenant: TenantContext) -> dict[UUID, str]:
        items, _total = await document_repo.list_documents(tenant, offset=0, limit=500)
        titles: dict[UUID, str] = {}
        for item in items:
            name = (item.title or "").strip()
            if name:
                titles[item.document_id] = name
        return titles

    retrieve = RetrieveEvidenceService(
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=chunks,
        graph_store=graph,
        lexical_store=lexical,
        reranker=HeuristicReranker(),
        active_document_ids=active_document_ids,
        document_titles=document_titles,
    )
    query = QueryDocumentsService(
        retrieve,
        GenerateAnswerService(chat),
        document_titles=document_titles,
    )
    process = ProcessRegisteredDocumentService(
        document_repo=document_repo,
        ingestion_repo=ingestion_repo,
        object_store=object_store,
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=chunks,
        lexical_store=lexical,
        graph_store=graph,
        chat_model=chat,
        structured_extractor=extractor,
        parsing_audit_repo=parsing_audit_repo,
        document_intelligence_provider=document_intelligence_provider,
        document_extraction_repo=document_extraction_repo,
        max_pages=max_pages,
        vision_max_pages=vision_max_pages_value,
        semantic_graph=enable_semantic_graph,
        on_commit=on_commit,
        parse_service=_parse_service_from_registry(parser_registry),
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
        chunk_store=chunks,
        lexical_store=lexical,
        cache=InMemoryCacheInvalidator(),
        chunk_id_provider=chunk_ids_for_version,
    )
    reindex_service = ReindexDocumentService(
        document_repo=document_repo,
        ingestion_repo=ingestion_repo,
        vector_store=vectors,
        graph_store=graph,
    )
    container = ServiceContainer(
        tenant_repo=tenant_repo,
        document_repo=document_repo,
        ingestion_repo=ingestion_repo,
        chat_project_repo=chat_project_repo,
        chat_conversation_repo=chat_conversation_repo,
        document_intelligence_model_repo=document_intelligence_model_repo,
        object_store=object_store,
        register_source=register,
        retrieve=retrieve,
        query=query,
        graph_store=graph,
        vector_store=vectors,
        chunk_store=chunks,
        delete_document=delete_service,
        reindex_document=reindex_service,
        audit_store=InMemoryAuditStore(),
        parsing_audit_repo=parsing_audit_repo,
        usage_repo=usage_repo,
        process_ingestion=process,
        auto_process_ingest=auto_process_ingest,
        ready_checks=[lambda: True],
        parser_registry=parser_registry,
    )
    from graph_rag.application.authorization.service import PolicyAuthorizationService
    from graph_rag.application.quotas.service import InMemoryQuotaService

    container.authorization = authorization
    container.quotas = quotas
    container.on_commit = on_commit
    return container
