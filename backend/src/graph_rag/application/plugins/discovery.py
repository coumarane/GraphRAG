"""Entry-point discovery for ``graph_rag.*`` plugin groups."""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import EntryPoint, entry_points

PLUGIN_ENTRY_POINT_GROUPS: dict[str, str] = {
    "object_store": "graph_rag.object_store",
    "vector_store": "graph_rag.vector_store",
    "graph_store": "graph_rag.graph_store",
    "metadata_store": "graph_rag.metadata_store",
    "ingest_queue": "graph_rag.ingest_queue",
    "parser": "graph_rag.parser",
    "chat_model": "graph_rag.chat_model",
    "embedding_model": "graph_rag.embedding_model",
    "reranker": "graph_rag.reranker",
    "cli_plugins": "graph_rag.cli_plugins",
    "api_routers": "graph_rag.api_routers",
}


@lru_cache(maxsize=32)
def load_entry_points(group: str) -> tuple[EntryPoint, ...]:
    """Return installed entry points for ``group``, cached for process start."""
    return tuple(entry_points(group=group))


def clear_entry_point_cache() -> None:
    """Drop the discovery cache. Intended for tests."""
    load_entry_points.cache_clear()
