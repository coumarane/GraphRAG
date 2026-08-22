"""Plugin registry unit tests (Phase 0)."""

from __future__ import annotations

from typing import Any

import pytest

from graph_rag.application.plugins.descriptors import PluginDescriptor
from graph_rag.application.plugins.registry import PluginRegistry
from graph_rag.shared.exceptions import ConfigurationError


def _factory(
    name: str,
    *,
    capability: str = "object_store",
    trust_tier: str = "community",
) -> PluginDescriptor:
    return PluginDescriptor(
        plugin_name=name,
        capability=capability,
        trust_tier=trust_tier,  # type: ignore[arg-type]
        builder=lambda _settings: f"built-{name}",
    )


def test_resolve_core_plugin() -> None:
    registry: PluginRegistry[Any] = PluginRegistry("object_store")
    registry.register_core(_factory("minio", trust_tier="core"))
    assert registry.build("minio", settings=None) == "built-minio"
    assert registry.names() == ["minio"]


def test_discovered_cannot_shadow_core() -> None:
    registry: PluginRegistry[Any] = PluginRegistry("object_store")
    registry.register_core(_factory("minio", trust_tier="core"))
    with pytest.raises(ConfigurationError, match="cannot override a core plugin"):
        registry.register_discovered(_factory("minio", trust_tier="community"))


def test_allow_core_override() -> None:
    registry: PluginRegistry[Any] = PluginRegistry("object_store", allow_core_override=True)
    registry.register_core(_factory("minio", trust_tier="core"))
    registry.register_discovered(_factory("minio", trust_tier="community"))
    assert registry.build("minio", settings=None) == "built-minio"


def test_empty_allowlist_keeps_core_only() -> None:
    registry: PluginRegistry[Any] = PluginRegistry("parser", allowlist=[])
    registry.register_core(_factory("pdfium", capability="parser", trust_tier="core"))
    registry.register_discovered(_factory("echo", capability="parser", trust_tier="community"))
    assert registry.names() == ["pdfium"]


def test_none_allowlist_accepts_discovered() -> None:
    registry: PluginRegistry[Any] = PluginRegistry("parser", allowlist=None)
    registry.register_core(_factory("pdfium", capability="parser", trust_tier="core"))
    registry.register_discovered(_factory("echo", capability="parser", trust_tier="community"))
    assert "echo" in registry.names()


def test_explicit_allowlist_enables_named_plugin() -> None:
    registry: PluginRegistry[Any] = PluginRegistry("parser", allowlist=["echo"])
    registry.register_core(_factory("pdfium", capability="parser", trust_tier="core"))
    registry.register_discovered(_factory("echo", capability="parser", trust_tier="community"))
    registry.register_discovered(_factory("other", capability="parser", trust_tier="community"))
    assert registry.names() == ["echo", "pdfium"]


def test_unknown_name_lists_available() -> None:
    registry: PluginRegistry[Any] = PluginRegistry("object_store")
    registry.register_core(_factory("memory", trust_tier="core"))
    with pytest.raises(ConfigurationError, match="not registered"):
        registry.resolve("s3")
