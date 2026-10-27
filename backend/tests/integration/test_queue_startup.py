"""A required Redis that cannot be opened must not become an in-memory queue."""

from __future__ import annotations

import pytest

from graph_rag.application.runtime.runtime import _wire_ingest_queue
from graph_rag.config.settings import Settings
from graph_rag.infrastructure.persistence.redis import InMemoryStreamIngestionQueue
from graph_rag.shared.exceptions import ConfigurationError


class _Container:
    pass


@pytest.mark.integration
def test_unreachable_redis_exits_before_memory_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[object] = []
    real = InMemoryStreamIngestionQueue

    class Spy(real):
        def __init__(self, *args: object, **kwargs: object) -> None:
            created.append(self)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        "graph_rag.infrastructure.persistence.redis.InMemoryStreamIngestionQueue",
        Spy,
    )
    monkeypatch.setenv("INGEST_QUEUE_BACKEND", "redis")
    settings = Settings()
    settings.redis.url = settings.redis.url.__class__("redis://127.0.0.1:1/0")
    container = _Container()
    with pytest.raises(ConfigurationError):
        _wire_ingest_queue(
            container,  # type: ignore[arg-type]
            settings,
            raw_session=None,
            db_lock=None,
            on_commit=None,
        )
    assert created == []
    assert not isinstance(getattr(container, "ingest_queue", None), InMemoryStreamIngestionQueue)
