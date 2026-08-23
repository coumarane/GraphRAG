"""Document Intelligence plugin factories and runtime registry assembly.

Phase 1 scope: the registry, capability constant, and structural contract a
provider must satisfy -- no extraction logic. ``_InternalProvider.execute``
is filled in once the extraction chain (structured parser -> rules -> table
-> embedding -> LLM -> vision) is implemented in a later phase.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.application.plugins.descriptors import PluginDescriptor
from graph_rag.application.plugins.discovery import PLUGIN_ENTRY_POINT_GROUPS
from graph_rag.application.plugins.registry import PluginRegistry

DOCUMENT_INTELLIGENCE_CAPABILITY = "document_intelligence"


class DocumentIntelligencePluginMetadata(BaseModel):
    """Provider-agnostic plugin metadata surfaced to the ops API/frontend."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    enabled: bool
    version: str
    capabilities: list[str] = Field(default_factory=list)


@runtime_checkable
class DocumentIntelligencePlugin(Protocol):
    """Structural contract a Document Intelligence provider must satisfy."""

    def metadata(self) -> DocumentIntelligencePluginMetadata: ...

    def is_enabled(self, settings: Any) -> bool: ...

    def get_models(self) -> list[Any]: ...

    def get_capabilities(self) -> list[str]: ...

    def validate_configuration(self, settings: Any) -> None: ...

    def execute(self, request: Any) -> Any: ...


class _InternalProvider:
    """Placeholder ``internal`` provider registered in Phase 1.

    Satisfies ``DocumentIntelligencePlugin`` structurally so the registry and
    catalog wiring exist and are testable before any extraction chain does.
    """

    def metadata(self) -> DocumentIntelligencePluginMetadata:
        return DocumentIntelligencePluginMetadata(
            id="internal",
            name="Internal",
            description=("Built-in structured field extraction (parsers, rules, LLM, vision)."),
            enabled=True,
            version="0.0.0",
            capabilities=[],
        )

    def is_enabled(self, settings: Any) -> bool:
        document_intelligence = getattr(settings, "document_intelligence", None)
        if document_intelligence is None:
            return True
        return bool(document_intelligence.enabled)

    def get_models(self) -> list[Any]:
        return []

    def get_capabilities(self) -> list[str]:
        return []

    def validate_configuration(self, settings: Any) -> None:
        return None

    def execute(self, request: Any) -> Any:
        raise NotImplementedError("Document Intelligence extraction is not implemented yet")


def _internal_builder(settings: Any) -> Any:
    return _InternalProvider()


CORE_DOCUMENT_INTELLIGENCE_DESCRIPTORS: tuple[PluginDescriptor, ...] = (
    PluginDescriptor(
        plugin_name="internal",
        capability=DOCUMENT_INTELLIGENCE_CAPABILITY,
        trust_tier="core",
        builder=_internal_builder,
        modules=("builtins",),
        structured=True,
    ),
)


def document_intelligence_plugin_registry(*, settings: Any | None = None) -> PluginRegistry[Any]:
    """Core Document Intelligence factories plus discovered entry points."""
    enabled = True
    allow_core_override = False
    allowlist: list[str] | None = None
    if settings is not None:
        plugins = getattr(settings, "plugins", None)
        if plugins is not None:
            enabled = bool(plugins.enabled)
            allow_core_override = bool(plugins.allow_core_override)
            allowlist = plugins.allowlist
    registry: PluginRegistry[Any] = PluginRegistry(
        DOCUMENT_INTELLIGENCE_CAPABILITY,
        allow_core_override=allow_core_override,
        allowlist=allowlist,
        enabled=enabled,
    )
    for descriptor in CORE_DOCUMENT_INTELLIGENCE_DESCRIPTORS:
        registry.register_core(descriptor)
    registry.load_entry_points(PLUGIN_ENTRY_POINT_GROUPS["document_intelligence"])
    return registry
