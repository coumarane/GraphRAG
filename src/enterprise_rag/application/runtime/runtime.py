"""Runtime container for deployed / docker API processes."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

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
    """Return configured object-store backend name (``memory``, ``minio``, or ``azure_blob``)."""
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
    - ``OBJECT_STORE_BACKEND``: memory | minio | azure_blob
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
    elif obj_backend in {"azure_blob", "azure", "blob"}:
        from enterprise_rag.infrastructure.persistence.azure_blob import AzureBlobObjectStore

        object_store = AzureBlobObjectStore(resolved.azure_blob)
    elif obj_backend not in {"memory", "inmemory", "local"}:
        raise ValueError(
            f"Unsupported OBJECT_STORE_BACKEND={obj_backend!r}; use 'memory', 'minio', or 'azure_blob'"
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
    parsing_audit_repo = None
    usage_repo = None
    db_session: AsyncSession | None = None
    on_commit: Callable[[], Awaitable[None]] | None = None
    ready_checks: list = []
    user_repo = None

    meta_backend = metadata_store_backend()
    if meta_backend in {"postgres", "postgresql", "pg"}:
        import asyncio

        from enterprise_rag.infrastructure.persistence.postgres import (
            LockedAsyncProxy,
            SqlAlchemyDocumentRepository,
            SqlAlchemyIngestionRepository,
            SqlAlchemyTenantRepository,
            create_engine,
            create_session_factory,
        )
        from enterprise_rag.infrastructure.persistence.postgres.repositories.parsing_audit import (
            SqlAlchemyParsingAuditRepository,
        )
        from enterprise_rag.infrastructure.persistence.postgres.repositories.usage import (
            SqlAlchemyUsageRepository,
        )
        from enterprise_rag.infrastructure.persistence.users import SqlAlchemyUserRepository

        engine = create_engine(resolved.postgres)
        session_factory = create_session_factory(engine)
        # This container lives for the whole process, but uvicorn (API) and
        # the ingestion worker's background tasks touch its single session
        # concurrently. AsyncSession isn't safe for that. Repositories are
        # wrapped (not the raw session) so a whole repo method call — e.g.
        # the sync `add()` followed by `await flush()` — is one atomic
        # locked unit; repos are built on the *raw* session internally so
        # they don't try to re-acquire the same lock their own call holds.
        db_lock = asyncio.Lock()
        raw_session = session_factory()
        tenant_repo = LockedAsyncProxy(SqlAlchemyTenantRepository(raw_session), db_lock)
        document_repo = LockedAsyncProxy(SqlAlchemyDocumentRepository(raw_session), db_lock)
        ingestion_repo = LockedAsyncProxy(SqlAlchemyIngestionRepository(raw_session), db_lock)
        parsing_audit_repo = LockedAsyncProxy(
            SqlAlchemyParsingAuditRepository(raw_session), db_lock
        )
        usage_repo = LockedAsyncProxy(SqlAlchemyUsageRepository(raw_session), db_lock)
        user_repo = LockedAsyncProxy(SqlAlchemyUserRepository(raw_session), db_lock)
        db_session = LockedAsyncProxy(raw_session, db_lock)

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
    else:
        from enterprise_rag.infrastructure.persistence.users import InMemoryUserRepository

        user_repo = InMemoryUserRepository()

    container = build_local_container(
        max_upload_bytes=resolved.security.max_upload_bytes,
        object_store=object_store,
        vector_store=vector_store,
        graph_store=graph_store,
        tenant_repo=tenant_repo,
        document_repo=document_repo,
        ingestion_repo=ingestion_repo,
        parsing_audit_repo=parsing_audit_repo,
        usage_repo=usage_repo,
        auto_process_ingest=os.environ.get("INGEST_EXECUTION", "worker").strip().lower()
        in {"inline", "inprocess", "api"},
        use_live_models=True,
        max_pages=resolved.security.max_pages,
        on_commit=on_commit,
        enable_semantic_graph=os.environ.get("SEMANTIC_GRAPH", "true").strip().lower()
        not in {"0", "false", "no"},
    )
    if ready_checks:
        container.ready_checks = list(container.ready_checks) + ready_checks
    container.db_session = db_session
    container.user_repo = user_repo
    if resolved.security.auth_enabled:
        from enterprise_rag.application.auth import AuthService
        from enterprise_rag.domain.auth.passwords import is_weak_jwt_secret
        from enterprise_rag.shared.exceptions import ConfigurationError

        if is_weak_jwt_secret(resolved.security.auth_jwt_secret):
            raise ConfigurationError(
                "AUTH_ENABLED requires a strong AUTH_JWT_SECRET (min 32 characters)"
            )
        if user_repo is None:
            raise ConfigurationError("AUTH_ENABLED requires a user repository")
        # Ensure memory mode also has a tenant repo for bootstrap.
        if container.tenant_repo is None:
            from enterprise_rag.infrastructure.persistence.memory import (
                InMemoryTenantRepository,
            )

            container.tenant_repo = InMemoryTenantRepository()
        container.auth_service = AuthService(
            users=user_repo,
            tenants=container.tenant_repo,
            jwt_secret=resolved.security.auth_jwt_secret,
            jwt_ttl_seconds=resolved.security.auth_jwt_ttl_seconds,
        )
    _wire_ingest_queue(
        container,
        resolved,
        raw_session=raw_session if meta_backend in {"postgres", "postgresql", "pg"} else None,
        db_lock=db_lock if meta_backend in {"postgres", "postgresql", "pg"} else None,
        on_commit=on_commit,
    )
    return container


def _wire_ingest_queue(
    container: ServiceContainer,
    settings: Settings,
    *,
    raw_session: AsyncSession | None,
    db_lock: Any | None,
    on_commit: Callable[[], Awaitable[None]] | None,
) -> None:
    from enterprise_rag.application.ingestion.outbox_publisher import OutboxPublisher
    from enterprise_rag.infrastructure.persistence.dead_letters import (
        InMemoryDeadLetterStore,
        SqlAlchemyDeadLetterStore,
    )
    from enterprise_rag.infrastructure.persistence.outbox import (
        InMemoryOutboxStore,
        SqlAlchemyOutboxStore,
    )
    from enterprise_rag.infrastructure.persistence.postgres import LockedAsyncProxy
    from enterprise_rag.infrastructure.persistence.redis import InMemoryStreamIngestionQueue

    if raw_session is not None and db_lock is not None:
        container.outbox_store = LockedAsyncProxy(SqlAlchemyOutboxStore(raw_session), db_lock)
        container.dead_letter_store = LockedAsyncProxy(
            SqlAlchemyDeadLetterStore(raw_session), db_lock
        )
    else:
        container.outbox_store = InMemoryOutboxStore()
        container.dead_letter_store = InMemoryDeadLetterStore()

    queue_backend = os.environ.get("INGEST_QUEUE_BACKEND", "").strip().lower()
    use_redis = queue_backend in {"redis", "streams"} or (
        not queue_backend and raw_session is not None
    )
    redis_client = None
    if use_redis:
        try:
            import redis.asyncio as redis_async

            redis_client = redis_async.from_url(
                settings.redis.url.get_secret_value(),
                decode_responses=False,
            )
        except Exception:
            redis_client = None
    if redis_client is not None:
        from enterprise_rag.infrastructure.persistence.redis import RedisStreamIngestionQueue

        container.ingest_queue = RedisStreamIngestionQueue(
            redis_client,
            stream_key=settings.worker.stream_key,
            group_name=settings.worker.consumer_group,
            consumer_name=settings.worker.consumer_name or "api-publisher",
        )
    else:
        container.ingest_queue = InMemoryStreamIngestionQueue(
            stream_key=settings.worker.stream_key,
            group_name=settings.worker.consumer_group,
            consumer_name=settings.worker.consumer_name or "api-publisher",
        )

    async def _load_run_status(tenant_id, run_id):
        if container.ingestion_repo is None:
            return None
        from enterprise_rag.domain.tenant import TenantContext

        run = await container.ingestion_repo.get_run(TenantContext(tenant_id=tenant_id), run_id)
        return None if run is None else run.status

    container.outbox_publisher = OutboxPublisher(
        container.outbox_store,
        container.ingest_queue,
        on_commit=on_commit,
        load_run_status=_load_run_status,
    )
