"""MinerU (magic_pdf / mineru) conversion into parser payload dicts."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from enterprise_rag.infrastructure.parsers.payload_pages import build_pages_from_elements
from enterprise_rag.shared.exceptions import ConfigurationError, ParserError

_TYPE_MAP = {
    "text": "text",
    "plain_text": "text",
    "paragraph": "text",
    "title": "heading",
    "heading": "heading",
    "list": "list",
    "index": "list",
    "table": "table",
    "image": "image",
    "figure": "image",
    "picture": "image",
    "chart": "chart",
    "equation": "equation",
    "inline_equation": "equation",
    "interline_equation": "equation",
    "formula": "equation",
    "caption": "caption",
    "table_caption": "caption",
    "image_caption": "caption",
    "footnote": "footnote",
    "code": "code",
    "header": "page_header",
    "page_header": "page_header",
    "footer": "page_footer",
    "page_footer": "page_footer",
}


def _page_number(item: dict[str, Any]) -> int:
    if "page_idx" in item and item["page_idx"] is not None:
        try:
            return int(item["page_idx"]) + 1
        except (TypeError, ValueError):
            pass
    for key in ("page_number", "page"):
        if key in item and item[key] is not None:
            try:
                return max(1, int(item[key]))
            except (TypeError, ValueError):
                continue
    return 1


def content_list_to_payload(
    items: list[Any],
    *,
    filename: str,
    page_count: int | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Map MinerU ``content_list`` JSON into the shared convert payload."""
    elements: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        raw_type = str(
            item.get("type") or item.get("category") or item.get("block_type") or "text"
        ).lower()
        mapped = _TYPE_MAP.get(raw_type, "text")
        page = _page_number(item)
        text = (
            item.get("text")
            or item.get("content")
            or item.get("table_body")
            or item.get("latex")
            or item.get("html")
            or ""
        )
        text = str(text).strip()
        if not text and mapped in {"text", "heading", "caption", "list"}:
            continue
        if not text and mapped in {"image", "chart", "figure"}:
            text = str(item.get("img_caption") or item.get("image_caption") or "").strip()
        meta: dict[str, Any] = {"mineru_type": raw_type}
        if item.get("img_path"):
            meta["img_path"] = item["img_path"]
        if item.get("latex"):
            meta["latex"] = item["latex"]
        elements.append(
            {
                "type": mapped,
                "text": text,
                "page": page,
                "reading_order": index,
                "section_path": [f"Page {page}"],
                "metadata": meta,
            }
        )

    inferred_pages = max((int(el["page"]) for el in elements), default=1)
    count = max(int(page_count or 0), inferred_pages, 1)
    return {
        "parser_version": "mineru",
        "title": filename,
        "page_count": count,
        "pages": build_pages_from_elements(elements, page_count=count),
        "elements": elements,
        "warnings": list(warnings or []),
        "metadata": {"parser": "mineru", "source": "mineru_content_list"},
    }


def markdown_to_payload(
    markdown: str,
    *,
    filename: str,
    page_count: int = 1,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Fallback: split markdown into coarse heading/text elements (page provenance weak)."""
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
    notes.append("mineru_page_provenance_unavailable")
    count = max(page_count, 1)
    return {
        "parser_version": "mineru",
        "title": filename,
        "page_count": count,
        "pages": build_pages_from_elements(elements, page_count=count),
        "elements": elements,
        "warnings": notes,
        "metadata": {"parser": "mineru"},
    }


def _find_content_list(out_dir: Path) -> Path | None:
    candidates = sorted(out_dir.rglob("*content_list.json"))
    if candidates:
        return candidates[0]
    for path in out_dir.rglob("*.json"):
        if "content" in path.name.lower() or "middle" in path.name.lower():
            return path
    return None


def _find_markdown(out_dir: Path) -> Path | None:
    mds = sorted(out_dir.rglob("*.md"))
    return mds[0] if mds else None


def _run_mineru_cli(pdf_path: Path, out_dir: Path) -> None:
    commands = [
        ["mineru", "-p", str(pdf_path), "-o", str(out_dir), "-m", "auto"],
        ["magic-pdf", "-p", str(pdf_path), "-o", str(out_dir), "-m", "auto"],
    ]
    last_error: Exception | None = None
    for cmd in commands:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise ParserError("MinerU CLI conversion failed", cause=last_error)
    raise ConfigurationError(
        "MinerU is not installed (package 'mineru' / 'magic_pdf' or CLI not found)",
        details={"extra": "parsers-mineru"},
    )


def _try_python_api(pdf_path: Path, out_dir: Path) -> bool:
    """Best-effort in-process MinerU call across evolving package names."""
    try:
        import mineru  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        try:
            import magic_pdf  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return False

    try:
        from magic_pdf.data.data_reader_writer import FileBasedDataWriter  # type: ignore
        from magic_pdf.data.dataset import PymuDocDataset  # type: ignore
        from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze  # type: ignore

        writer = FileBasedDataWriter(str(out_dir))
        dataset = PymuDocDataset(pdf_path.read_bytes())
        infer = dataset.apply(doc_analyze, ocr=True)
        pipe = infer.pipe_ocr_mode(writer) if hasattr(infer, "pipe_ocr_mode") else infer
        if hasattr(pipe, "dump_content_list"):
            pipe.dump_content_list(writer, f"{pdf_path.stem}_content_list.json")
            return True
    except Exception:
        return False
    return False


def mineru_convert(data: bytes, filename: str) -> dict[str, Any]:
    """Convert PDF bytes with MinerU into the shared intermediate payload."""
    suffix = Path(filename).suffix or ".pdf"
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="mineru-") as tmp:
        root = Path(tmp)
        pdf_path = root / f"input{suffix}"
        out_dir = root / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(data)

        if shutil.which("mineru") or shutil.which("magic-pdf"):
            _run_mineru_cli(pdf_path, out_dir)
        else:
            if not _try_python_api(pdf_path, out_dir):
                raise ConfigurationError(
                    "Optional dependency for MinerU is not installed",
                    details={"extra": "parsers-mineru", "module": "mineru"},
                )

        content_list_path = _find_content_list(out_dir)
        if content_list_path is not None:
            payload = json.loads(content_list_path.read_text(encoding="utf-8"))
            items = payload if isinstance(payload, list) else payload.get("content_list") or []
            if not isinstance(items, list):
                raise ParserError(
                    "MinerU content_list JSON has unexpected shape",
                    details={"path": str(content_list_path)},
                )
            return content_list_to_payload(
                items,
                filename=filename,
                warnings=warnings,
            )

        md_path = _find_markdown(out_dir)
        if md_path is not None:
            return markdown_to_payload(
                md_path.read_text(encoding="utf-8"),
                filename=filename,
                warnings=warnings + ["mineru_content_list_missing"],
            )

        raise ParserError(
            "MinerU finished without content_list.json or markdown output",
            details={"out_dir": str(out_dir)},
        )
