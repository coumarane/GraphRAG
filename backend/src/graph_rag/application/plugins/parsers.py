"""Core parser plugin factories and runtime parser-registry assembly."""

from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Collection, Mapping
from typing import Any

from graph_rag.application.plugins.descriptors import PluginDescriptor
from graph_rag.application.plugins.discovery import PLUGIN_ENTRY_POINT_GROUPS
from graph_rag.application.plugins.registry import PluginRegistry
from graph_rag.domain.parsing.types import parser_key
from graph_rag.shared.exceptions import ConfigurationError

PARSER_CAPABILITY = "parser"


def _pdfium_builder(settings: Any) -> Any:
    from graph_rag.infrastructure.parsers.pdfium import PdfiumInspector, PdfiumParser

    return PdfiumParser(inspector=PdfiumInspector())


def _text_builder(settings: Any) -> Any:
    from graph_rag.infrastructure.parsers.pdfium import PdfiumInspector
    from graph_rag.infrastructure.parsers.text import TextDocumentParser

    return TextDocumentParser(inspector=PdfiumInspector())


def _docling_builder(settings: Any) -> Any:
    from graph_rag.infrastructure.parsers.docling import DoclingParser
    from graph_rag.infrastructure.parsers.pdfium import PdfiumInspector

    return DoclingParser(inspector=PdfiumInspector())


def _mineru_builder(settings: Any) -> Any:
    from graph_rag.infrastructure.parsers.mineru import MinerUParser
    from graph_rag.infrastructure.parsers.pdfium import PdfiumInspector

    return MinerUParser(inspector=PdfiumInspector())


def _marker_builder(settings: Any) -> Any:
    from graph_rag.infrastructure.parsers.marker import MarkerParser
    from graph_rag.infrastructure.parsers.pdfium import PdfiumInspector

    return MarkerParser(inspector=PdfiumInspector())


def _paddleocr_builder(settings: Any) -> Any:
    from graph_rag.infrastructure.parsers.paddleocr import PaddleOCRParser
    from graph_rag.infrastructure.parsers.pdfium import PdfiumInspector

    return PaddleOCRParser(inspector=PdfiumInspector())


CORE_PARSER_DESCRIPTORS: tuple[PluginDescriptor, ...] = (
    PluginDescriptor(
        plugin_name="pdfium",
        capability=PARSER_CAPABILITY,
        trust_tier="core",
        builder=_pdfium_builder,
        extra="parsers",
        modules=("pypdfium2",),
        structured=False,
    ),
    PluginDescriptor(
        plugin_name="text",
        capability=PARSER_CAPABILITY,
        trust_tier="core",
        builder=_text_builder,
        modules=("builtins",),
        structured=True,
    ),
    PluginDescriptor(
        plugin_name="docling",
        capability=PARSER_CAPABILITY,
        trust_tier="core",
        builder=_docling_builder,
        extra="parsers-docling",
        modules=("docling",),
        structured=True,
    ),
    PluginDescriptor(
        plugin_name="mineru",
        capability=PARSER_CAPABILITY,
        trust_tier="core",
        builder=_mineru_builder,
        extra="parsers-mineru",
        modules=("mineru", "magic_pdf"),
        structured=True,
    ),
    PluginDescriptor(
        plugin_name="marker",
        capability=PARSER_CAPABILITY,
        trust_tier="core",
        builder=_marker_builder,
        extra="parsers-marker",
        modules=("marker",),
        structured=True,
    ),
    PluginDescriptor(
        plugin_name="paddleocr",
        capability=PARSER_CAPABILITY,
        trust_tier="core",
        builder=_paddleocr_builder,
        extra="parsers-ocr",
        modules=("paddleocr",),
        structured=True,
    ),
)


def core_parser_descriptor_map() -> dict[str, PluginDescriptor]:
    return {item.plugin_name: item for item in CORE_PARSER_DESCRIPTORS}


def structured_parser_names() -> frozenset[str]:
    return frozenset(item.plugin_name for item in CORE_PARSER_DESCRIPTORS if item.structured)


def _module_available(name: str) -> bool:
    if name == "builtins":
        return True
    return importlib.util.find_spec(name) is not None


def descriptor_is_installed(descriptor: PluginDescriptor) -> bool:
    """Return True when the adapter's optional SDK (or CLI) is present."""
    if descriptor.plugin_name == "mineru":
        if any(_module_available(module) for module in descriptor.modules):
            return True
        return shutil.which("mineru") is not None or shutil.which("magic-pdf") is not None
    if not descriptor.modules:
        return True
    return any(_module_available(module) for module in descriptor.modules)


def parser_is_installed(
    name: str,
    *,
    descriptors: Mapping[str, PluginDescriptor] | None = None,
) -> bool:
    key = parser_key(name)
    specs = descriptors if descriptors is not None else core_parser_descriptor_map()
    spec = specs.get(key)
    if spec is None:
        return True
    return descriptor_is_installed(spec)


def is_structured_parser(
    name: str,
    *,
    descriptors: Mapping[str, PluginDescriptor] | None = None,
) -> bool:
    key = parser_key(name)
    specs = descriptors if descriptors is not None else core_parser_descriptor_map()
    spec = specs.get(key)
    if spec is None:
        return key != "pdfium"
    return spec.structured


def parser_plugin_registry(*, settings: Any | None = None) -> PluginRegistry[Any]:
    """Core parser factories plus discovered ``graph_rag.parser`` entry points."""
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
        PARSER_CAPABILITY,
        allow_core_override=allow_core_override,
        allowlist=allowlist,
        enabled=enabled,
    )
    for descriptor in CORE_PARSER_DESCRIPTORS:
        registry.register_core(descriptor)
    registry.load_entry_points(PLUGIN_ENTRY_POINT_GROUPS["parser"])
    return registry


def build_core_parser_instances(settings: Any | None = None) -> dict[str, Any]:
    """Construct the six in-tree parsers with no entry-point scan."""
    return {item.plugin_name: item.build(settings) for item in CORE_PARSER_DESCRIPTORS}


def build_parser_instances(
    settings: Any | None = None,
    *,
    discover: bool = False,
) -> dict[str, Any]:
    """Construct parser adapters.

    ``discover=False`` (default) is core-only so unit tests and
    ``build_local_container()`` stay free of entry-point I/O.
    """
    if not discover:
        return build_core_parser_instances(settings)
    registry = parser_plugin_registry(settings=settings)
    return {name: descriptor.build(settings) for name, descriptor in registry.descriptors().items()}


def resolve_inspector_name(
    registered: Collection[str],
    *,
    configured: str | None = None,
) -> str:
    """Choose the inspect() parser. Default: docling if present, else pdfium."""
    names = {parser_key(item) for item in registered}
    if configured:
        key = parser_key(configured)
        if key not in names:
            raise ConfigurationError(
                "Configured parser inspector is not registered",
                details={"inspector": key, "available": sorted(names)},
            )
        return key
    if "docling" in names:
        return "docling"
    if "pdfium" in names:
        return "pdfium"
    if names:
        return sorted(names)[0]
    raise ConfigurationError("No parser inspector is available")


def configured_inspector_name(settings: Any | None) -> str | None:
    if settings is None:
        return None
    plugins = getattr(settings, "plugins", None)
    if plugins is None:
        return None
    parser_cfg = (plugins.config or {}).get("parser") or {}
    if not isinstance(parser_cfg, dict):
        return None
    raw = parser_cfg.get("inspector")
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip().lower()


def validate_parsing_profile_primaries(
    profiles: Mapping[str, Any],
    registered: Collection[str],
) -> None:
    """Fail startup when a profile primary is not a registered parser name."""
    names = {parser_key(item) for item in registered}
    for profile_name, profile in profiles.items():
        primary = parser_key(getattr(profile, "primary", profile))
        if primary not in names:
            raise ConfigurationError(
                "Parser profile primary is not registered",
                details={
                    "profile": profile_name,
                    "primary": primary,
                    "available": sorted(names),
                },
            )
