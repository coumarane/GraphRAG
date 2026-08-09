"""Docling parser adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from enterprise_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParseSource,
    RawParserResult,
)
from enterprise_rag.infrastructure.parsers.base import require_optional_dependency, run_parser_sync
from enterprise_rag.infrastructure.parsers.convert import dict_to_raw_result
from enterprise_rag.infrastructure.parsers.pdfium.inspector import PdfiumInspector

DoclingConvertFn = Callable[[bytes, str], dict[str, Any]]

_LABEL_TYPE_MAP: dict[str, str] = {
    "title": "heading",
    "section_header": "heading",
    "heading": "heading",
    "paragraph": "text",
    "text": "text",
    "caption": "caption",
    "footnote": "footnote",
    "page_header": "page_header",
    "page_footer": "page_footer",
    "list_item": "list",
    "list": "list",
    "table": "table",
    "picture": "image",
    "figure": "image",
    "image": "image",
    "chart": "chart",
    "formula": "equation",
    "equation": "equation",
    "code": "code",
}


def _pdf_page_count(data: bytes) -> int | None:
    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(data)
        try:
            return len(document)
        finally:
            document.close()
    except Exception:
        return None


def _page_from_item(item: Any) -> int | None:
    prov = getattr(item, "prov", None)
    if not prov:
        return None
    entries = prov if isinstance(prov, (list, tuple)) else [prov]
    for entry in entries:
        page = getattr(entry, "page_no", None)
        if page is None:
            page = getattr(entry, "page_number", None)
        if page is None:
            page = getattr(entry, "page", None)
        if page is None:
            continue
        page_i = int(page)
        # Docling provenance page_no is 1-based in current releases.
        return page_i if page_i >= 1 else page_i + 1
    return None


def _item_text(item: Any) -> str:
    text = getattr(item, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    export = getattr(item, "export_to_markdown", None)
    if callable(export):
        try:
            exported = export()
            if isinstance(exported, str) and exported.strip():
                return exported.strip()
        except Exception:
            pass
    return ""


def _map_label(label: str) -> str:
    key = label.strip().lower().replace(" ", "_").replace("-", "_")
    return _LABEL_TYPE_MAP.get(key, "text")


def _default_docling_convert(data: bytes, filename: str) -> dict[str, Any]:
    require_optional_dependency("docling", extra_name="parsers-docling")
    # Lazy import of Docling APIs. Exact API surface varies by version; adapters
    # normalize into a stable intermediate dict for conversion.
    import tempfile
    from pathlib import Path

    from docling.document_converter import DocumentConverter  # type: ignore[import-not-found]

    converter = DocumentConverter()
    suffix = Path(filename).suffix or ".pdf"
    warnings: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(data)
        handle.flush()
        result = converter.convert(handle.name)
    document = result.document

    elements: list[dict[str, Any]] = []
    pages_seen: set[int] = set()
    iterate = getattr(document, "iterate_items", None)
    if callable(iterate):
        for index, pair in enumerate(iterate()):
            item = pair[0] if isinstance(pair, tuple) and pair else pair
            label_obj = getattr(item, "label", None)
            label = str(getattr(label_obj, "value", label_obj) or type(item).__name__)
            text = _item_text(item)
            page = _page_from_item(item) or 1
            pages_seen.add(page)
            # Skip empty structural wrappers; keep tables/images even without text.
            mapped = _map_label(label)
            if not text and mapped in {"text", "heading", "caption", "list"}:
                continue
            elements.append(
                {
                    "type": mapped,
                    "text": text,
                    "page": page,
                    "reading_order": index,
                    "metadata": {"docling_label": label},
                }
            )

    if not elements:
        # Legacy fallback: markdown blocks (page provenance unavailable).
        export = getattr(document, "export_to_markdown", None)
        markdown = export() if callable(export) else str(document)
        for index, block in enumerate(part for part in markdown.split("\n\n") if part.strip()):
            elements.append(
                {
                    "type": "heading" if block.lstrip().startswith("#") else "text",
                    "text": block.lstrip("# ").strip(),
                    "page": 1,
                    "reading_order": index,
                }
            )
        warnings.append("docling_page_provenance_unavailable")

    page_count = 0
    num_pages = getattr(document, "num_pages", None)
    if callable(num_pages):
        try:
            page_count = int(num_pages())
        except Exception:
            page_count = 0
    if page_count <= 0 and pages_seen:
        page_count = max(pages_seen)
    if filename.lower().endswith(".pdf"):
        pdf_pages = _pdf_page_count(data)
        if pdf_pages is not None:
            if page_count <= 0:
                page_count = pdf_pages
            elif pdf_pages > page_count:
                # Prefer the true PDF length for audit/reporting completeness.
                page_count = pdf_pages
                warnings.append(f"docling_page_count_raised_to_pdfium_{pdf_pages}")

    if page_count <= 0:
        page_count = max((int(item.get("page", 1) or 1) for item in elements), default=1)

    pages = [{"page_number": number} for number in range(1, page_count + 1)]
    return {
        "parser_version": getattr(DocumentConverter, "__module__", "docling"),
        "title": filename,
        "page_count": page_count,
        "pages": pages,
        "elements": elements,
        "warnings": warnings,
    }


class DoclingParser:
    """Docling adapter for enterprise PDFs and office documents."""

    name = ParserName.DOCLING.value

    def __init__(
        self,
        inspector: PdfiumInspector | None = None,
        convert_fn: DoclingConvertFn | None = None,
    ) -> None:
        self._inspector = inspector or PdfiumInspector()
        self._convert_fn = convert_fn or _default_docling_convert

    async def inspect(self, source: ParseSource) -> ParserInspection:
        return await self._inspector.inspect(source)

    async def parse(self, source: ParseSource, options: ParseOptions) -> RawParserResult:
        data = source.require_bytes()
        payload = await run_parser_sync(lambda: self._convert_fn(data, source.filename))
        return dict_to_raw_result(self.name, payload)
