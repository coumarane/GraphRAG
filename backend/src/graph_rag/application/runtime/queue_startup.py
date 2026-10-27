"""Fail closed when the ingest queue must be Redis and cannot be opened.

ADR 0002: a process that cannot open Redis must not serve. Disabling only the
ingest routes would leave a ready API that can still accept a job into memory
if a later code path falls back. Readiness of the whole process is what keeps
that pod out of rotation. Queries continue on any replica whose Redis client
did open. A Redis outage after startup leaves accepted rows on the outbox.
"""

from __future__ import annotations

import os

from graph_rag.config.settings import Settings
from graph_rag.shared.exceptions import ConfigurationError
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)


def redis_queue_required(*, metadata_is_postgres: bool) -> bool:
    backend = os.environ.get("INGEST_QUEUE_BACKEND", "").strip().lower()
    if backend in {"memory", "inmemory"}:
        return False
    if backend in {"redis", "streams"}:
        return True
    return metadata_is_postgres


def open_redis_or_raise(settings: Settings) -> None:
    """Ping Redis. Constructor-only clients are not enough; ``from_url`` does not connect."""
    import redis

    url = settings.redis.url.get_secret_value()
    client = redis.Redis.from_url(url, socket_connect_timeout=2, decode_responses=False)
    try:
        client.ping()
    except Exception as exc:
        logger.error("ingest_queue_startup_failed", error_type=type(exc).__name__)
        raise ConfigurationError(
            "Ingest queue Redis could not be opened",
            details={"error_type": type(exc).__name__},
        ) from exc
    client.close()
