"""PaddleOCR PDF/image conversion into parser payload dicts."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from graph_rag.domain.parsing.types import ParseOptions
from graph_rag.shared.exceptions import ConfigurationError, ParserError


def paddleocr_convert(data: bytes, filename: str, options: ParseOptions) -> dict[str, Any]:
    """Render PDF pages (or decode an image) and OCR with PaddleOCR."""
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise ConfigurationError(
            "Optional dependency 'paddleocr' is not installed",
            details={"extra": "parsers-ocr", "module": "paddleocr"},
            cause=exc,
        ) from exc
    try:
        import numpy as np
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ConfigurationError(
            "PaddleOCR conversion requires pypdfium2 and numpy",
            cause=exc,
        ) from exc

    lowered = filename.lower()
    is_pdf = lowered.endswith(".pdf") or data[:4] == b"%PDF"
    max_pages = 2_000
    meta_max = options.metadata.get("max_pages") if options.metadata else None
    if isinstance(meta_max, int) and meta_max > 0:
        max_pages = meta_max

    # PaddleOCR 2.x API; keep CPU-only for local/dev reliability.
    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

    images: list[tuple[int, Any]] = []
    page_sizes: dict[int, tuple[float, float]] = {}
    if is_pdf:
        document = pdfium.PdfDocument(data)
        try:
            limit = min(len(document), max_pages)
            for index in range(limit):
                page = document[index]
                try:
                    width, height = page.get_size()
                    page_sizes[index + 1] = (float(width), float(height))
                    bitmap = page.render(scale=1.5)
                    pil = bitmap.to_pil().convert("RGB")
                    images.append((index + 1, np.asarray(pil)))
                finally:
                    page.close()
        finally:
            document.close()
    else:
        try:
            from PIL import Image
        except ImportError as exc:
            raise ConfigurationError("Pillow is required for image OCR", cause=exc) from exc
        pil = Image.open(BytesIO(data)).convert("RGB")
        images.append((1, np.asarray(pil)))
        page_sizes[1] = (float(pil.width), float(pil.height))

    if not images:
        raise ParserError("No pages available for OCR", details={"filename": filename})

    elements: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    order = 0
    for page_number, image in images:
        try:
            result = ocr.ocr(image, cls=True)
        except Exception as exc:  # noqa: BLE001
            raise ParserError(
                "PaddleOCR failed on page",
                details={"filename": filename, "page": page_number},
                cause=exc,
            ) from exc
        lines: list[str] = []
        confidences: list[float] = []
        page_result = result[0] if result else None
        if page_result:
            for item in page_result:
                if not item or len(item) < 2:
                    continue
                text_info = item[1]
                text = str(text_info[0]).strip() if text_info else ""
                if not text:
                    continue
                conf = float(text_info[1]) if text_info and len(text_info) > 1 else 0.0
                lines.append(text)
                confidences.append(conf)
                elements.append(
                    {
                        "type": "text",
                        "page": page_number,
                        "reading_order": order,
                        "text": text,
                        "ocr_confidence": conf,
                        "section_path": [f"Page {page_number}"],
                    }
                )
                order += 1
        joined = "\n".join(lines)
        width, height = page_sizes.get(page_number, (0.0, 0.0))
        pages.append(
            {
                "page_number": page_number,
                "width": width,
                "height": height,
                "text_density": float(len(joined)),
                "image_coverage": 0.95,
                "is_scanned": True,
                "ocr_confidence": (
                    sum(confidences) / len(confidences) if confidences else None
                ),
            }
        )
        # Mark the page as visual so hybrid vision can prioritize + stamp it.
        elements.append(
            {
                "type": "image",
                "page": page_number,
                "reading_order": order,
                "text": "",
                "section_path": [f"Page {page_number}"],
                "metadata": {
                    "source": "paddleocr_page_image",
                    "ocr_line_count": len(lines),
                },
            }
        )
        order += 1

    if not elements:
        raise ParserError(
            "PaddleOCR produced no text",
            details={"filename": filename, "pages": len(pages)},
        )

    return {
        "page_count": len(pages),
        "pages": pages,
        "elements": elements,
        "warnings": [],
        "metadata": {
            "ocr_engine": "paddleocr",
            "page_texts": {
                str(page["page_number"]): "\n".join(
                    el["text"]
                    for el in elements
                    if el["page"] == page["page_number"]
                    and el.get("type") != "image"
                    and el.get("text")
                )[:4000]
                for page in pages
            },
        },
    }
