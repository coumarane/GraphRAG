"""Detect which optional parser SDKs can actually import."""

from __future__ import annotations

from typing import Any

from graph_rag.application.plugins.parsers import (
    core_parser_descriptor_map,
    descriptor_is_installed,
)
from graph_rag.application.plugins.parsers import (
    parser_is_installed as plugin_parser_is_installed,
)


def parser_is_installed(name: str) -> bool:
    """Return True when the adapter's optional SDK (or CLI) is present."""
    return plugin_parser_is_installed(name)


def parser_extra_name(name: str) -> str | None:
    spec = core_parser_descriptor_map().get(name.strip().lower())
    return spec.extra if spec is not None else None


def installed_parsers() -> dict[str, bool]:
    """Map parser name → importable/available."""
    return {
        name: descriptor_is_installed(spec)
        for name, spec in core_parser_descriptor_map().items()
    }


def parser_status_payload() -> dict[str, Any]:
    """Operator-facing snapshot for health/diagnostics."""
    installed = installed_parsers()
    missing = [
        {"parser": name, "extra": parser_extra_name(name)}
        for name, ok in installed.items()
        if not ok and name not in {"text", "pdfium"}
    ]
    return {"installed": installed, "missing": missing}
