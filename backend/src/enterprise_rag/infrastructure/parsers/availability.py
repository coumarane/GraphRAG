"""Detect which optional parser SDKs can actually import."""

from __future__ import annotations

import importlib.util
import shutil
from typing import Any

from enterprise_rag.domain.parsing.types import ParserName

_MODULE_BY_PARSER: dict[str, tuple[str, ...]] = {
    ParserName.DOCLING.value: ("docling",),
    ParserName.MINERU.value: ("mineru", "magic_pdf"),
    ParserName.MARKER.value: ("marker",),
    ParserName.PADDLEOCR.value: ("paddleocr",),
    ParserName.PDFIUM.value: ("pypdfium2",),
    ParserName.TEXT.value: ("builtins",),
}

_EXTRA_BY_PARSER: dict[str, str] = {
    ParserName.DOCLING.value: "parsers-docling",
    ParserName.MINERU.value: "parsers-mineru",
    ParserName.MARKER.value: "parsers-marker",
    ParserName.PADDLEOCR.value: "parsers-ocr",
    ParserName.PDFIUM.value: "parsers",
}


def _module_available(name: str) -> bool:
    if name == "builtins":
        return True
    return importlib.util.find_spec(name) is not None


def parser_is_installed(name: str) -> bool:
    """Return True when the adapter's optional SDK (or CLI) is present."""
    key = name.strip().lower()
    if key == ParserName.MINERU.value:
        if any(_module_available(module) for module in _MODULE_BY_PARSER[key]):
            return True
        return shutil.which("mineru") is not None or shutil.which("magic-pdf") is not None
    modules = _MODULE_BY_PARSER.get(key)
    if not modules:
        return False
    return any(_module_available(module) for module in modules)


def parser_extra_name(name: str) -> str | None:
    return _EXTRA_BY_PARSER.get(name.strip().lower())


def installed_parsers() -> dict[str, bool]:
    """Map parser name → importable/available."""
    names = [
        ParserName.DOCLING.value,
        ParserName.MINERU.value,
        ParserName.MARKER.value,
        ParserName.PADDLEOCR.value,
        ParserName.PDFIUM.value,
        ParserName.TEXT.value,
    ]
    return {name: parser_is_installed(name) for name in names}


def parser_status_payload() -> dict[str, Any]:
    """Operator-facing snapshot for health/diagnostics."""
    installed = installed_parsers()
    missing = [
        {"parser": name, "extra": parser_extra_name(name)}
        for name, ok in installed.items()
        if not ok and name not in {ParserName.TEXT.value, ParserName.PDFIUM.value}
    ]
    return {"installed": installed, "missing": missing}
