"""Runtime container for deployed / docker API processes."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from enterprise_rag.application.runtime.container import ServiceContainer
from enterprise_rag.application.runtime.local import build_local_container
from enterprise_rag.config.settings import Settings, get_settings
from enterprise_rag.domain.ingestion.protocols import (
    DocumentRepository,
    IngestionRepository,
    TenantRepository,
)
from enterprise_rag.infrastructure.persistence.minio import MinioObjectStore


def object_store_backend() -> str:
    """Return configured object-store backend name (``memory`` or ``minio``)."""
    return os.environ.get("OBJECT_STORE_BACKEND", "memory").strip().lower() or "memory"


def vector_store_backend() -> str:
    """Return vector backend name (``memory`` or ``qdrant``)."""
    return os.environ.get("VECTOR_STORE_BACKEND", "memory").strip().lower() or "memory"


def graph_store_backend() -> str:
    """Return graph backend name (``memory`` or ``neo4j``)."""
    return os.environ.get("GRAPH_STORE_BACKEND", "memory").strip().lower() or "memory"


def metadata_store_backend() -> str:
    """Return metadata backend name (``memory`` or ``postgres``)."""
    return os.environ.get("METADATA_STORE_BACKEND", "memory").strip().lower() or "memory"


def build_runtime_container(settings: Settings | None = None) -> ServiceContainer:
    """Build the process container for uvicorn / compose.

    Backends (env):
    - ``OBJECT_STORE_BACKEND``: memory | minio
    - ``VECTOR_STORE_BACKEND``: memory | qdrant
    - ``GRAPH_STORE_BACKEND``: memory | neo4j
    - ``METADATA_STORE_BACKEND``: memory | postgres
    """
    resolved = settings or get_settings()
    _ = resolved

    object_store = None
    obj_backend = object_store_backend()
    if obj_backend == "minio":
        object_store = MinioObjectStore(resolved.minio)
    elif obj_backend not in {"memory", "inmemory", "local"}:
        raise ValueError(
            f"Unsupported OBJECT_STORE_BACKEND={obj_backend!r}; use 'memory' or 'minio'"
        )

    vector_store = None
    vec_backend = vector_store_backend()
    if vec_backend == "qdrant":
        from enterprise_rag.infrastructure.persistence.qdrant import QdrantChunkVectorStore

        vector_store = QdrantChunkVectorStore(resolved.qdrant)
    elif vec_backend not in {"memory", "inmemory", "local"}:
        raise ValueError(
            f"Unsupported VECTOR_STORE_BACKEND={vec_backend!r}; use 'memory' or 'qdrant'"
        )

    graph_store = None
    graph_backend = graph_store_backend()
    if graph_backend == "neo4j":
        from enterprise_rag.infrastructure.persistence.neo4j import Neo4jGraphStore

        graph_store = Neo4jGraphStore(resolved.neo4j)
    elif graph_backend not in {"memory", "inmemory", "local"}:
        raise ValueError(
            f"Unsupported GRAPH_STORE_BACKEND={graph_backend!r}; use 'memory' or 'neo4j'"
        )

    tenant_repo: TenantRepository | None = None
    document_repo: DocumentRepository | None = None
    ingestion_repo: IngestionRepository | None = None
    db_session: AsyncSession | None = None
    on_commit: Callable[[], Awaitable[None]] | None = None
    ready_checks: list = []

    meta_backend = metadata_store_backend()
    if meta_backend in {"postgres", "postgresql", "pg"}:
        from enterprise_rag.infrastructure.persistence.postgres import (
            SqlAlchemyDocumentRepository,
            SqlAlchemyIngestionRepository,
            SqlAlchemyTenantRepository,
            create_engine,
            create_session_factory,
        )

        engine = create_engine(resolved.postgres)
        session_factory = create_session_factory(engine)
        db_session = session_factory()
        tenant_repo = SqlAlchemyTenantRepository(db_session)
        document_repo = SqlAlchemyDocumentRepository(db_session)
        ingestion_repo = SqlAlchemyIngestionRepository(db_session)

        async def _commit() -> None:
            await db_session.commit()

        async def _postgres_ready() -> bool:
            from sqlalchemy import text

            try:
                await db_session.execute(text("SELECT 1"))
                return True
            except Exception:
                return False

        on_commit = _commit
        ready_checks.append(_postgres_ready)
    elif meta_backend not in {"memory", "inmemory", "local"}:
        raise ValueError(
            f"Unsupported METADATA_STORE_BACKEND={meta_backend!r}; use 'memory' or 'postgres'"
        )

    container = build_local_container(
        max_upload_bytes=resolved.security.max_upload_bytes,
        object_store=object_store,
        vector_store=vector_store,
        graph_store=graph_store,
        tenant_repo=tenant_repo,
        document_repo=document_repo,
        ingestion_repo=ingestion_repo,
        auto_process_ingest=True,
        use_live_models=True,
        max_pages=resolved.security.max_pages,
        on_commit=on_commit,
        enable_semantic_graph=os.environ.get("SEMANTIC_GRAPH", "true").strip().lower()
        not in {"0", "false", "no"},
    )
    if ready_checks:
        container.ready_checks = list(container.ready_checks) + ready_checks
    container.db_session = db_session
    return container
