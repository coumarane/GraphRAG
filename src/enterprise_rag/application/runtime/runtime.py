"""Runtime container for deployed / docker API processes."""

from __future__ import annotations

import os

from enterprise_rag.application.runtime.container import ServiceContainer
from enterprise_rag.application.runtime.local import build_local_container
from enterprise_rag.config.settings import Settings, get_settings
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


def build_runtime_container(settings: Settings | None = None) -> ServiceContainer:
    """Build the process container for uvicorn / compose.

    Backends (env):
    - ``OBJECT_STORE_BACKEND``: memory | minio
    - ``VECTOR_STORE_BACKEND``: memory | qdrant
    - ``GRAPH_STORE_BACKEND``: memory | neo4j

    Document/ingestion metadata remain in-memory until Postgres wiring lands.
    """
    resolved = settings or get_settings()
    # Ensure flat .env keys (OBJECT_STORE_BACKEND, etc.) are visible to helpers.
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

    return build_local_container(
        max_upload_bytes=resolved.security.max_upload_bytes,
        object_store=object_store,
        vector_store=vector_store,
        graph_store=graph_store,
        auto_process_ingest=True,
        use_live_models=True,
        max_pages=resolved.security.max_pages,
    )
