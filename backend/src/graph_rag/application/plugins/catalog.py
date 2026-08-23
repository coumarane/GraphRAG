"""Read-only plugin inventory for ops API and CLI introspection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.application.plugins.descriptors import TrustTier
from graph_rag.application.plugins.document_intelligence import (
    DOCUMENT_INTELLIGENCE_CAPABILITY,
    document_intelligence_plugin_registry,
)
from graph_rag.application.plugins.parsers import (
    CORE_PARSER_DESCRIPTORS,
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
DiscoverableStatus = Literal["missing_extra", "blocked", "not_registered"]

_STORE_CAPABILITIES: tuple[str, ...] = (
    "object_store",
    "vector_store",
    "graph_store",
    "metadata_store",
    "ingest_queue",
)

_DOCS_PLUGIN_PLAN = "/docs/plugin-architecture-plan.md"
_DOCS_API_VERSIONING = "/docs/plugin-api-versioning.md"

# Known packaging extras / third-party slots operators may want to enable.
# Core parser extras come from CORE_PARSER_DESCRIPTORS; this list holds
# additional discoverable names that are not always registered in-process.
_KNOWN_DISCOVERABLE: tuple[dict[str, Any], ...] = (
    {
        "plugin_name": "mcp",
        "capability": "mcp",
        "trust_tier": "core",
        "extra": "mcp",
        "docs_url": "/docs/mcp-server.md",
        "install_hint": (
            "Install optional extra 'mcp' (`uv sync --extra mcp`) and set "
            "MCP_ENABLED=true on the API; Docker images already include the extra."
        ),
    },
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
    install_hint: str | None = None


class DiscoverablePlugin(BaseModel):
    """Known plugin/extra that needs operator action to become usable."""

    model_config = ConfigDict(extra="forbid")

    plugin_name: str
    capability: str
    trust_tier: TrustTier
    status: DiscoverableStatus
    extra: str | None = None
    install_hint: str
    docs_url: str | None = None


class PluginCatalog(BaseModel):
    """Host plugin settings plus discovered factories."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    allow_core_override: bool = False
    allowlist: list[str] | None = None
    selections: list[PluginSelection] = Field(default_factory=list)
    items: list[PluginItem] = Field(default_factory=list)
    discoverable: list[DiscoverablePlugin] = Field(default_factory=list)


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
    if DOCUMENT_INTELLIGENCE_CAPABILITY not in resolved:
        resolved[DOCUMENT_INTELLIGENCE_CAPABILITY] = document_intelligence_plugin_registry(
            settings=settings
        )

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
                    allowlist=allowlist,
                )
            )
        for descriptor in registry.blocked().values():
            items.append(
                _item(
                    registry,
                    descriptor,
                    enabled=False,
                    selected=False,
                    allowlist=allowlist,
                )
            )

    items.sort(key=lambda item: (item.capability, item.plugin_name))
    discoverable = _build_discoverable(items, allowlist=allowlist)
    return PluginCatalog(
        enabled=enabled,
        allow_core_override=allow_core_override,
        allowlist=None if allowlist is None else list(allowlist),
        selections=selections,
        items=items,
        discoverable=discoverable,
    )


def _install_hint(
    *,
    enabled: bool,
    installed: bool,
    plugin_name: str,
    extra: str | None,
    allowlist: list[str] | None,
) -> str | None:
    if not enabled:
        if allowlist is not None and len(allowlist) == 0:
            return (
                f"Blocked by plugins.allowlist=[] (core-only). Add '{plugin_name}' "
                "to allowlist, or set allowlist: null in development."
            )
        return (
            f"Blocked by plugins.allowlist. Add '{plugin_name}' to "
            "plugins.allowlist in YAML, then restart the API/worker."
        )
    if not installed:
        if extra:
            return (
                f"Optional extra '{extra}' is not installed in this image. "
                f"Add it to the Docker build (`uv sync --extra {extra}`) and redeploy; "
                f"see {_DOCS_PLUGIN_PLAN}."
            )
        return (
            f"Required modules for '{plugin_name}' are missing from this process. "
            f"Rebuild the image with the plugin dependencies; see {_DOCS_API_VERSIONING}."
        )
    return None


def _item(
    registry: PluginRegistry[Any],
    descriptor: Any,
    *,
    enabled: bool,
    selected: bool,
    allowlist: list[str] | None,
) -> PluginItem:
    origin: PluginOrigin = (
        "discovered" if registry.origin_of(descriptor.plugin_name) == "discovered" else "core"
    )
    installed = descriptor_is_installed(descriptor)
    return PluginItem(
        plugin_name=descriptor.plugin_name,
        capability=descriptor.capability,
        trust_tier=descriptor.trust_tier,
        origin=origin,
        enabled=enabled,
        installed=installed,
        extra=descriptor.extra,
        modules=list(descriptor.modules or ()),
        structured=bool(descriptor.structured),
        selected=selected,
        install_hint=_install_hint(
            enabled=enabled,
            installed=installed,
            plugin_name=descriptor.plugin_name,
            extra=descriptor.extra,
            allowlist=allowlist,
        ),
    )


def _build_discoverable(
    items: list[PluginItem],
    *,
    allowlist: list[str] | None,
) -> list[DiscoverablePlugin]:
    """Surface plugins needing operator action plus known-but-unregistered slots."""
    by_key = {(item.capability, item.plugin_name): item for item in items}
    rows: list[DiscoverablePlugin] = []

    for item in items:
        if not item.enabled:
            rows.append(
                DiscoverablePlugin(
                    plugin_name=item.plugin_name,
                    capability=item.capability,
                    trust_tier=item.trust_tier,
                    status="blocked",
                    extra=item.extra,
                    install_hint=item.install_hint
                    or f"Add '{item.plugin_name}' to plugins.allowlist.",
                    docs_url=_DOCS_PLUGIN_PLAN,
                )
            )
        elif not item.installed:
            rows.append(
                DiscoverablePlugin(
                    plugin_name=item.plugin_name,
                    capability=item.capability,
                    trust_tier=item.trust_tier,
                    status="missing_extra",
                    extra=item.extra,
                    install_hint=item.install_hint
                    or f"Install dependencies for '{item.plugin_name}'.",
                    docs_url=_DOCS_PLUGIN_PLAN,
                )
            )

    # Ensure every core parser with an optional extra appears as discoverable
    # when its modules are absent, even if a custom registry omitted it.
    for descriptor in CORE_PARSER_DESCRIPTORS:
        key = (descriptor.capability, descriptor.plugin_name)
        if key in by_key:
            continue
        if not descriptor.extra:
            continue
        if descriptor_is_installed(descriptor):
            continue
        rows.append(
            DiscoverablePlugin(
                plugin_name=descriptor.plugin_name,
                capability=descriptor.capability,
                trust_tier=descriptor.trust_tier,
                status="not_registered",
                extra=descriptor.extra,
                install_hint=_install_hint(
                    enabled=True,
                    installed=False,
                    plugin_name=descriptor.plugin_name,
                    extra=descriptor.extra,
                    allowlist=allowlist,
                )
                or f"Install optional extra '{descriptor.extra}'.",
                docs_url=_DOCS_PLUGIN_PLAN,
            )
        )

    for known in _KNOWN_DISCOVERABLE:
        key = (str(known["capability"]), str(known["plugin_name"]))
        if key in by_key:
            continue
        if any(row.capability == key[0] and row.plugin_name == key[1] for row in rows):
            continue
        # MCP slot is only "to discover" when the server is not enabled yet.
        if key == ("mcp", "mcp"):
            from graph_rag.application.plugins.mcp_ops import mcp_enabled_from_env

            if mcp_enabled_from_env():
                continue
        rows.append(
            DiscoverablePlugin(
                plugin_name=str(known["plugin_name"]),
                capability=str(known["capability"]),
                trust_tier=cast(TrustTier, known["trust_tier"]),
                status="not_registered",
                extra=known.get("extra"),
                install_hint=str(known["install_hint"]),
                docs_url=known.get("docs_url"),
            )
        )

    rows.sort(key=lambda row: (row.capability, row.plugin_name))
    return rows


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
                rows.append(PluginSelection(capability=capability, name=backend, role="backend"))

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
