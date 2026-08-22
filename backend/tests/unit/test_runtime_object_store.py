"""Runtime container object-store selection."""

from __future__ import annotations

import pytest

from graph_rag.application.runtime.local import build_local_container
from graph_rag.application.runtime.runtime import (
    build_runtime_container,
    object_store_backend,
)
from graph_rag.config.settings import Settings
from graph_rag.infrastructure.persistence.memory import InMemoryObjectStore
from graph_rag.infrastructure.persistence.minio import MinioObjectStore


def test_object_store_backend_defaults_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OBJECT_STORE_BACKEND", raising=False)
    assert object_store_backend() == "memory"


def test_build_runtime_container_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "memory")
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "memory")
    monkeypatch.setenv("GRAPH_STORE_BACKEND", "memory")
    container = build_runtime_container(Settings())
    assert isinstance(container.object_store, InMemoryObjectStore)


def test_build_runtime_container_minio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "minio")
    monkeypatch.setenv("VECTOR_STORE_BACKEND", "memory")
    monkeypatch.setenv("GRAPH_STORE_BACKEND", "memory")
    container = build_runtime_container(Settings())
    assert isinstance(container.object_store, MinioObjectStore)


def test_build_local_container_accepts_custom_object_store() -> None:
    store = InMemoryObjectStore()
    container = build_local_container(object_store=store)
    assert container.object_store is store
