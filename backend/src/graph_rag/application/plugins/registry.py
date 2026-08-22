"""Generic named plugin registry with core-vs-discovered merge rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from graph_rag.application.plugins import discovery as plugin_discovery
from graph_rag.application.plugins.descriptors import PluginDescriptor, TrustTier
from graph_rag.shared.exceptions import ConfigurationError


class PluginRegistry[T]:
    """One registry per capability (parser, object_store, ...).

    Core factories are in-tree. Discovered entry points cannot shadow a core
    name unless ``allow_core_override`` is true.
    """

    def __init__(
        self,
        capability: str,
        *,
        allow_core_override: bool = False,
        allowlist: list[str] | None = None,
        enabled: bool = True,
    ) -> None:
        self.capability = capability
        self.allow_core_override = allow_core_override
        self.allowlist = allowlist
        self.enabled = enabled
        self._core: dict[str, PluginDescriptor] = {}
        self._discovered: dict[str, PluginDescriptor] = {}
        self._blocked: dict[str, PluginDescriptor] = {}

    def register_core(self, descriptor: PluginDescriptor) -> None:
        """Register a built-in factory. Last writer for a core name wins."""
        self._check_capability(descriptor)
        self._core[descriptor.plugin_name] = descriptor

    def register_discovered(self, descriptor: PluginDescriptor) -> None:
        """Register a third-party factory, enforcing shadowing and allowlist."""
        self._check_capability(descriptor)
        name = descriptor.plugin_name
        if descriptor.trust_tier == "core":
            raise ConfigurationError(
                "Discovered plugin cannot declare core trust tier",
                details={"capability": self.capability, "plugin": name},
            )
        if name in self._core and not self.allow_core_override:
            raise ConfigurationError(
                "Discovered plugin cannot override a core plugin",
                details={
                    "capability": self.capability,
                    "plugin": name,
                    "allow_core_override": False,
                },
            )
        if not self._is_allowed(name, descriptor.trust_tier):
            self._blocked[name] = descriptor
            return
        self._blocked.pop(name, None)
        self._discovered[name] = descriptor

    def load_entry_points(self, group: str) -> None:
        """Load ``group`` entry points when plugins are enabled."""
        if not self.enabled:
            return
        for entry in plugin_discovery.load_entry_points(group):
            loaded = entry.load()
            descriptor = _as_descriptor(loaded, fallback_name=entry.name)
            self.register_discovered(descriptor)

    def resolve(self, name: str) -> PluginDescriptor:
        """Return the factory for ``name`` or raise ``ConfigurationError``."""
        key = name.strip().lower()
        try:
            return self.merged()[key]
        except KeyError as exc:
            raise ConfigurationError(
                "Plugin is not registered",
                details={
                    "capability": self.capability,
                    "plugin": key,
                    "available": self.names(),
                },
            ) from exc

    def build(self, name: str, settings: Any) -> T:
        """Construct the adapter for ``name``."""
        return self.resolve(name).build(settings)  # type: ignore[no-any-return]

    def merged(self) -> dict[str, PluginDescriptor]:
        """Core factories, then discovered (discovered may replace when allowed)."""
        merged = dict(self._core)
        merged.update(self._discovered)
        return merged

    def names(self) -> list[str]:
        return sorted(self.merged())

    def descriptors(self) -> Mapping[str, PluginDescriptor]:
        return self.merged()

    def blocked(self) -> Mapping[str, PluginDescriptor]:
        """Discovered factories skipped by the allowlist (not in ``merged()``)."""
        return dict(self._blocked)

    def origin_of(self, name: str) -> str:
        """Return ``core`` or ``discovered`` for a registered or blocked name."""
        if name in self._discovered or name in self._blocked:
            return "discovered"
        return "core"

    def _is_allowed(self, name: str, trust_tier: str) -> bool:
        # trust_tier is never "core" here: register_discovered rejects that
        # before this is called, and register_core never calls this at all.
        del trust_tier
        if self.allowlist is None:
            return True
        return name in self.allowlist

    def _check_capability(self, descriptor: PluginDescriptor) -> None:
        if descriptor.capability != self.capability:
            raise ConfigurationError(
                "Plugin capability does not match registry",
                details={
                    "registry": self.capability,
                    "plugin": descriptor.plugin_name,
                    "capability": descriptor.capability,
                },
            )


def _as_descriptor(loaded: object, *, fallback_name: str) -> PluginDescriptor:
    if isinstance(loaded, PluginDescriptor):
        return loaded
    plugin_name = str(getattr(loaded, "plugin_name", fallback_name)).strip().lower()
    capability = str(getattr(loaded, "capability", "")).strip()
    raw_tier = getattr(loaded, "trust_tier", "community")
    trust_tier = cast(
        TrustTier,
        raw_tier if raw_tier in {"core", "verified", "community"} else "community",
    )
    builder = getattr(loaded, "build", None)
    if not callable(builder):
        raise ConfigurationError(
            "Plugin entry point must expose build(settings)",
            details={"plugin": plugin_name},
        )
    return PluginDescriptor(
        plugin_name=plugin_name,
        capability=capability,
        builder=builder,
        trust_tier=trust_tier,
        config_model=getattr(loaded, "config_model", None),
        extra=getattr(loaded, "extra", None),
        modules=tuple(getattr(loaded, "modules", ()) or ()),
        structured=bool(getattr(loaded, "structured", False)),
    )
