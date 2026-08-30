"""Document Intelligence plugin registry/catalog/settings tests (Phase 1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from graph_rag.application.plugins.catalog import build_plugin_catalog
from graph_rag.application.plugins.document_intelligence import (
    CORE_DOCUMENT_INTELLIGENCE_DESCRIPTORS,
    DOCUMENT_INTELLIGENCE_CAPABILITY,
    DocumentIntelligencePlugin,
    document_intelligence_plugin_registry,
)
from graph_rag.config.settings import DocumentIntelligenceSettings, Settings


def test_internal_provider_satisfies_plugin_protocol() -> None:
    descriptor = next(
        item for item in CORE_DOCUMENT_INTELLIGENCE_DESCRIPTORS if item.plugin_name == "internal"
    )
    provider = descriptor.build(settings=None)
    assert isinstance(provider, DocumentIntelligencePlugin)
    metadata = provider.metadata()
    assert metadata.id == "internal"
    assert metadata.enabled is True


def test_internal_provider_execute_is_not_implemented_yet() -> None:
    descriptor = next(
        item for item in CORE_DOCUMENT_INTELLIGENCE_DESCRIPTORS if item.plugin_name == "internal"
    )
    provider = descriptor.build(settings=None)
    with pytest.raises(NotImplementedError):
        provider.execute(request=None)


def test_registry_defaults_to_enabled_with_no_settings() -> None:
    registry = document_intelligence_plugin_registry(settings=None)
    assert registry.names() == ["internal"]
    assert registry.capability == DOCUMENT_INTELLIGENCE_CAPABILITY


def test_registry_respects_empty_allowlist() -> None:
    settings = SimpleNamespace(
        plugins=SimpleNamespace(enabled=True, allow_core_override=False, allowlist=[])
    )
    registry = document_intelligence_plugin_registry(settings=settings)
    # "internal" is a core plugin, so the allowlist (which only gates
    # discovered plugins) does not block it.
    assert registry.names() == ["internal"]


def test_catalog_includes_document_intelligence_capability() -> None:
    catalog = build_plugin_catalog(SimpleNamespace(plugins=None, parsing=None))
    item = next(row for row in catalog.items if row.capability == DOCUMENT_INTELLIGENCE_CAPABILITY)
    assert item.plugin_name == "internal"
    assert item.origin == "core"


def test_document_intelligence_settings_defaults() -> None:
    settings = Settings()
    assert isinstance(settings.document_intelligence, DocumentIntelligenceSettings)
    assert settings.document_intelligence.enabled is True
    assert settings.document_intelligence.default_provider == "internal"
