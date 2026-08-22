"""Marker PDF conversion into parser payload dicts."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from graph_rag.infrastructure.parsers.payload_pages import build_pages_from_elements
from graph_rag.shared.exceptions import ConfigurationError, ParserError

_BLOCK_TYPE_MAP = {
    "text": "text",
    "textblock": "text",
    "paragraph": "text",
    "sectionheader": "heading",
    "section_header": "heading",
    "title": "heading",
    "heading": "heading",
    "listitem": "list",
    "list_item": "list",
    "listgroup": "list",
    "table": "table",
    "tablecell": "table",
    "picture": "image",
    "figure": "image",
    "image": "image",
    "figuregroup": "image",
    "equation": "equation",
    "formulablock": "equation",
    "code": "code",
    "caption": "caption",
    "footnote": "footnote",
    "pageheader": "page_header",
    "pagefooter": "page_footer",
}


def _map_block_type(raw: str) -> str:
    key = raw.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    # Normalize common variants after stripping underscores.
    aliases = {
        "sectionheader": "heading",
        "listitem": "list",
        "listgroup": "list",
        "tablecell": "table",
        "figuregroup": "image",
        "formulablock": "equation",
        "pageheader": "page_header",
        "pagefooter": "page_footer",
    }
    if key in aliases:
        return aliases[key]
    return _BLOCK_TYPE_MAP.get(raw.strip().lower().replace(" ", "_"), "text")


def _block_text(node: dict[str, Any]) -> str:
    for key in ("html", "text", "markdown", "content", "latex"):
        value = node.get(key)
        if value:
            return str(value).strip()
    return ""


def _page_from_node(node: dict[str, Any], default: int = 1) -> int:
    for key in ("page", "page_id", "page_number", "page_idx"):
        if key in node and node[key] is not None:
            try:
                value = int(node[key])
            except (TypeError, ValueError):
                continue
            if key == "page_idx":
                return value + 1
            return max(1, value)
    return default


def marker_blocks_to_payload(
    root: dict[str, Any] | list[Any],
    *,
    filename: str,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Flatten Marker JSON/block trees into the shared convert payload."""
    elements: list[dict[str, Any]] = []

    def walk(node: Any, *, default_page: int = 1) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child, default_page=default_page)
            return
        if not isinstance(node, dict):
            return
        page = _page_from_node(node, default_page)
        raw_type = str(
            node.get("block_type")
            or node.get("type")
            or node.get("id")
            or "text"
        )
        # Marker often uses enum-like "BlockTypes.Text"
        if "." in raw_type:
            raw_type = raw_type.rsplit(".", 1)[-1]
        mapped = _map_block_type(raw_type)
        text = _block_text(node)
        children = node.get("children")
        has_children = isinstance(children, list) and bool(children)
        leafish = mapped in {
            "text",
            "heading",
            "list",
            "table",
            "image",
            "chart",
            "equation",
            "caption",
            "footnote",
            "code",
            "page_header",
            "page_footer",
        }
        if leafish and (text or mapped in {"image", "chart", "table", "equation"}):
            elements.append(
                {
                    "type": mapped,
                    "text": text,
                    "page": page,
                    "reading_order": len(elements),
                    "section_path": [f"Page {page}"],
                    "metadata": {"marker_type": raw_type},
                }
            )
        if has_children:
            walk(children, default_page=page)

    if isinstance(root, dict) and "children" in root:
        walk(root)
    else:
        walk(root)

    if not elements and isinstance(root, dict):
        md = root.get("markdown") or root.get("text")
        if isinstance(md, str) and md.strip():
            return marker_markdown_to_payload(
                md,
                filename=filename,
                warnings=(warnings or []) + ["marker_json_empty_blocks"],
            )

    count = max((int(el["page"]) for el in elements), default=1)
    return {
        "parser_version": "marker",
        "title": filename,
        "page_count": count,
        "pages": build_pages_from_elements(elements, page_count=count),
        "elements": elements,
        "warnings": list(warnings or []),
        "metadata": {"parser": "marker"},
    }


def marker_markdown_to_payload(
    markdown: str,
    *,
    filename: str,
    page_count: int = 1,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    for index, block in enumerate(part for part in markdown.split("\n\n") if part.strip()):
        stripped = block.strip()
        is_heading = stripped.startswith("#")
        elements.append(
            {
                "type": "heading" if is_heading else "text",
                "text": stripped.lstrip("# ").strip(),
                "page": 1,
                "reading_order": index,
                "section_path": ["Page 1"],
            }
        )
    notes = list(warnings or [])
    notes.append("marker_page_provenance_unavailable")
    count = max(page_count, 1)
    return {
        "parser_version": "marker",
        "title": filename,
        "page_count": count,
        "pages": build_pages_from_elements(elements, page_count=count),
        "elements": elements,
        "warnings": notes,
        "metadata": {"parser": "marker"},
    }


def marker_convert(data: bytes, filename: str) -> dict[str, Any]:
    """Convert PDF bytes with Marker into the shared intermediate payload."""
    try:
        from marker.converters.pdf import PdfConverter  # type: ignore[import-not-found]
        from marker.models import create_model_dict  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ConfigurationError(
            "Optional dependency 'marker' / 'marker-pdf' is not installed",
            details={"extra": "parsers-marker", "module": "marker"},
            cause=exc,
        ) from exc

    suffix = Path(filename).suffix or ".pdf"
    warnings: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(data)
        handle.flush()
        try:
            # Prefer JSON when supported for structured blocks + pages.
            try:
                from marker.config.parser import ConfigParser  # type: ignore[import-not-found]

                config_parser = ConfigParser({"output_format": "json"})
                converter = PdfConverter(
                    config=config_parser.generate_config_dict(),
                    artifact_dict=create_model_dict(),
                    processor_list=config_parser.get_processors(),
                    renderer=config_parser.get_renderer(),
                )
            except Exception:
                converter = PdfConverter(artifact_dict=create_model_dict())
            rendered = converter(handle.name)
        except Exception as exc:  # noqa: BLE001
            raise ParserError("Marker conversion failed", cause=exc) from exc

    if hasattr(rendered, "model_dump"):
        payload = rendered.model_dump()
    elif isinstance(rendered, dict):
        payload = rendered
    else:
        payload = {
            "markdown": getattr(rendered, "markdown", None),
            "children": getattr(rendered, "children", None),
            "metadata": getattr(rendered, "metadata", None),
        }

    if isinstance(payload.get("children"), list) or payload.get("block_type"):
        result = marker_blocks_to_payload(payload, filename=filename, warnings=warnings)
        if result["elements"]:
            return result

    markdown = payload.get("markdown")
    if isinstance(markdown, str) and markdown.strip():
        return marker_markdown_to_payload(
            markdown,
            filename=filename,
            warnings=warnings,
        )

    # Legacy helper path
    try:
        from marker.output import text_from_rendered  # type: ignore[import-not-found]

        text, _, _images = text_from_rendered(rendered)
        if text and str(text).strip():
            return marker_markdown_to_payload(
                str(text),
                filename=filename,
                warnings=warnings + ["marker_text_from_rendered"],
            )
    except Exception:
        pass

    raise ParserError("Marker produced no structured content or markdown")
