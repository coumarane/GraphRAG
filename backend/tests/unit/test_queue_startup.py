"""Redis is required to be reachable before the process serves."""

import pytest

from graph_rag.application.runtime.queue_startup import open_redis_or_raise, redis_queue_required
from graph_rag.config.settings import Settings
from graph_rag.shared.exceptions import ConfigurationError


def test_redis_required_when_backend_is_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGEST_QUEUE_BACKEND", "redis")
    assert redis_queue_required(metadata_is_postgres=False) is True


def test_memory_backend_is_not_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGEST_QUEUE_BACKEND", "memory")
    assert redis_queue_required(metadata_is_postgres=True) is False


def test_unreachable_redis_refuses_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGEST_QUEUE_BACKEND", "redis")
    settings = Settings()
    settings.redis.url = settings.redis.url.__class__("redis://127.0.0.1:1/0")
    with pytest.raises(ConfigurationError):
        open_redis_or_raise(settings)
