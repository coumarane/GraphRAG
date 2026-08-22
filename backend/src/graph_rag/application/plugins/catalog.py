"""Read-only plugin inventory for ops API and CLI introspection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.application.plugins.descriptors import TrustTier
from graph_rag.application.plugins.parsers import (
    PARSER_CAPABILITY,
    configured_inspector_name,
    descriptor_is_installed,
    parser_plugin_registry,
    resolve_inspector_name,
)
from graph_rag.application.plugins.registry import PluginRegistry
from graph_rag.domain.parsing.types import parser_key
from graph_rag.shared.exceptions import ConfigurationError

PluginOrigin = Literal["core", "discovered"]
SelectionRole = Literal["backend", "inspector", "profile_primary"]

_STORE_CAPABILITIES: tuple[str, ...] = (
    "object_store",
    "vector_store",
    "graph_store",
    "metadata_store",
    "ingest_queue",
)


class PluginSelection(BaseModel):
    """Configured name for a capability slot."""

    model_config = ConfigDict(extra="forbid")

    capability: str
    name: str
    role: SelectionRole = "backend"


class PluginItem(BaseModel):
    """One registered or allowlist-blocked plugin factory."""

    model_config = ConfigDict(extra="forbid")

    plugin_name: str
    capability: str
    trust_tier: TrustTier
    origin: PluginOrigin
    enabled: bool
    installed: bool
    extra: str | None = None
    modules: list[str] = Field(default_factory=list)
    structured: bool = False
    selected: bool = False


class PluginCatalog(BaseModel):
    """Host plugin settings plus discovered factories."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    allow_core_override: bool = False
    allowlist: list[str] | None = None
    selections: list[PluginSelection] = Field(default_factory=list)
    items: list[PluginItem] = Field(default_factory=list)


def build_plugin_catalog(
    settings: Any | None = None,
    *,
    registries: Mapping[str, PluginRegistry[Any]] | None = None,
) -> PluginCatalog:
    """Assemble the catalog from settings and capability registries.

    ``registries=None`` discovers parser entry points. Tests inject a hand-built
    registry to avoid packaging I/O.
    """
    plugins = getattr(settings, "plugins", None) if settings is not None else None
    enabled = True if plugins is None else bool(plugins.enabled)
    allow_core_override = False if plugins is None else bool(plugins.allow_core_override)
    allowlist = None if plugins is None else plugins.allowlist

    resolved = dict(registries or {})
    if PARSER_CAPABILITY not in resolved:
        resolved[PARSER_CAPABILITY] = parser_plugin_registry(settings=settings)

    selections = _selections(settings, resolved.get(PARSER_CAPABILITY))
    selected_by_capability: dict[str, set[str]] = {}
    for selection in selections:
        selected_by_capability.setdefault(selection.capability, set()).add(selection.name)

    items: list[PluginItem] = []
    for registry in resolved.values():
        for name, descriptor in registry.descriptors().items():
            items.append(
                _item(
                    registry,
                    descriptor,
                    enabled=True,
                    selected=name in selected_by_capability.get(registry.capability, set()),
                )
            )
        for descriptor in registry.blocked().values():
            items.append(
                _item(
                    registry,
                    descriptor,
                    enabled=False,
                    selected=False,
                )
            )

    items.sort(key=lambda item: (item.capability, item.plugin_name))
    return PluginCatalog(
        enabled=enabled,
        allow_core_override=allow_core_override,
        allowlist=None if allowlist is None else list(allowlist),
        selections=selections,
        items=items,
    )


def _item(
    registry: PluginRegistry[Any],
    descriptor: Any,
    *,
    enabled: bool,
    selected: bool,
) -> PluginItem:
    origin: PluginOrigin = (
        "discovered" if registry.origin_of(descriptor.plugin_name) == "discovered" else "core"
    )
    return PluginItem(
        plugin_name=descriptor.plugin_name,
        capability=descriptor.capability,
        trust_tier=descriptor.trust_tier,
        origin=origin,
        enabled=enabled,
        installed=descriptor_is_installed(descriptor),
        extra=descriptor.extra,
        modules=list(descriptor.modules or ()),
        structured=bool(descriptor.structured),
        selected=selected,
    )


def _selections(
    settings: Any | None,
    parser_registry: PluginRegistry[Any] | None,
) -> list[PluginSelection]:
    rows: list[PluginSelection] = []
    plugins = getattr(settings, "plugins", None) if settings is not None else None
    if plugins is not None:
        for capability in _STORE_CAPABILITIES:
            selection = getattr(plugins, capability, None)
            backend = str(getattr(selection, "backend", "") or "").strip()
            if backend:
                rows.append(
                    PluginSelection(capability=capability, name=backend, role="backend")
                )

    if parser_registry is not None:
        registered = parser_registry.names()
        try:
            inspector = resolve_inspector_name(
                registered,
                configured=configured_inspector_name(settings),
            )
            rows.append(
                PluginSelection(capability=PARSER_CAPABILITY, name=inspector, role="inspector")
            )
        except ConfigurationError:
            pass

    parsing = getattr(settings, "parsing", None) if settings is not None else None
    if parsing is not None:
        profile_name = getattr(parsing, "default_profile", None)
        profiles = getattr(parsing, "profiles", None) or {}
        profile = profiles.get(profile_name) if profile_name else None
        if profile is not None:
            primary = parser_key(getattr(profile, "primary", profile))
            rows.append(
                PluginSelection(
                    capability=PARSER_CAPABILITY,
                    name=primary,
                    role="profile_primary",
                )
            )
    return rows
