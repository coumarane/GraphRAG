"""Classify visual regions and decide vision vs OCR."""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.elements.geometry import BoundingBox
from enterprise_rag.domain.parsing.types import RawElement, RawParserResult

_SEM_HINT = re.compile(
    r"(?i)\b(sem|tem|afm|xrd|stem|micrograph|microscope|electron\s+microscop|"
    r"scanning\s+electron|scale\s*bar|magnification|µm|nm\b)\b"
)
_FIGURE_HINT = re.compile(
    r"(?i)\b(sem|tem|xrd|afm|microscope|micrograph|figure|fig\.|chart|diagram|photo|"
    r"comparison|appearance|tone-?up|soft-?focus|angle of measurement|byk|l\*|mica|"
    r"map|factory|factories|head office|branch|laboratory|company introduction)\b"
)
_CHART_PAGE_HINT = re.compile(
    r"(?i)\b(comparison with|synthetic mica|soft-?focus|tone-?up|"
    r"angle of measurement|byk-?mac|transparent|gloss type|matte type|"
    r"natural tone|l\*\s*-?\s*15|measurement conditions)\b"
)
_PHOTO_HINT = re.compile(
    r"(?i)\b(photo|appearance|product\s+image|packshot|texture|skin|cosmetic)\b"
)
_PERCENT_TOKEN = re.compile(r"(?<!\d)\d{1,3}(?:\.\d+)?\s*%")
_FLAT_CHART_HINT = re.compile(
    r"(?i)\b("
    r"irritation|patch test|concentration level|response\s*,?\s*%|"
    r"bar chart|test report|human skin|no skin irritation|"
    r"moisture level|time after application|legend|control|"
    r"series|axis|ranking"
    r")\b"
)

KIND_PRIORITY = {
    "chart": 100,
    "sem": 90,
    "scan": 80,
    "diagram": 70,
    "table_image": 60,
    "photo": 50,
    "page": 40,
}

VISION_KINDS = frozenset(
    {"chart", "sem", "scan", "diagram", "table_image", "photo", "page"}
)

ELEMENT_VISION_PROMPT = """Analyze this cropped region from a technical PDF
(cosmetics, powders, chemicals, microscopy).
Return ONLY valid JSON (no markdown fences) with this shape:
{{
  "page_summary": "short summary of this region",
  "ocr_text": "ALL readable text in the crop, including titles, legends, axes, scale bars, labels",
  "measurement_conditions": "empty if none",
  "callouts": [],
  "tables": [],
  "formulas": [],
  "figures": [{{
    "type": "{kind}",
    "title": "",
    "description": "what this region shows",
    "ocr_labels": "",
    "numeric_precision": "exact|approximate",
    "values_markdown": "",
    "axes": {{}},
    "legend": [],
    "series_ranking": "",
    "gap_assessments": [],
    "trends": []
  }}]
}}
Nearby page context:
{context}

Rules:
- Kind hint for this crop is "{kind}". Honor it unless the pixels clearly
  show another type.
- For SEM/TEM/microscopy: describe morphology, particle shape/size, scale bar,
  magnification. Do not invent measurements that are not printed.
- For charts: capture axes, legend, series, and values_markdown.
- For photos/product shots: describe appearance, color, texture, packaging text.
- For logos, letterheads, or company/brand marks (a name next to an emblem,
  seal, or wordmark — often at the top of a slide or document): transcribe
  the exact company/organization name and any registered brand name verbatim
  into ocr_text, in every language shown (e.g. both the native-script and
  Romanized forms). Treat this as the primary fact to capture even if the
  rest of the crop is decorative.
- For scanned images: transcribe readable text faithfully; note unreadable regions.
- Never invent unseen numeric values.
"""


@dataclass(frozen=True)
class VisualTarget:
    """One region that needs OCR and/or vision."""

    kind: str
    tool: str
    page_number: int
    element_index: int | None
    bbox: BoundingBox | None
    nearby_text: str
    reason: str


def recommended_tool(kind: str) -> str:
    """Best processor for a visual kind.

    Scanned *text* is handled by PaddleOCR at parse time. Charts, SEM,
    photos, diagrams, and scan *images* need GPT vision.
    """
    if kind in VISION_KINDS:
        return "vision"
    return "ocr"


def looks_like_flat_chart_ocr(text: str) -> bool:
    """True when OCR flattened a chart into loose % labels without structure."""
    if not text or not text.strip():
        return False
    percent_count = len(_PERCENT_TOKEN.findall(text))
    if percent_count < 4:
        return False
    if _FLAT_CHART_HINT.search(text) or _CHART_PAGE_HINT.search(text):
        return True
    return percent_count >= 6 and bool(
        re.search(
            r"(?i)\b(25\s*%|50\s*%|75\s*%|concentration|comparison|vs\.?|versus)\b",
            text,
        )
    )


def classify_visual_kind(
    *,
    element: RawElement | None,
    context: str,
    page_is_scanned: bool = False,
) -> str:
    blob = " ".join(
        part
        for part in (
            context,
            (element.normalized_content if element else None) or "",
            (element.raw_content if element else None) or "",
            str((element.metadata if element else {}) or {}),
        )
        if part
    )
    if _SEM_HINT.search(blob):
        return "sem"
    if element is not None and element.element_type is ElementType.CHART:
        return "chart"
    if _CHART_PAGE_HINT.search(blob) or looks_like_flat_chart_ocr(blob):
        return "chart"
    if element is not None and element.element_type is ElementType.DIAGRAM:
        return "diagram"
    if page_is_scanned:
        return "scan"
    if _PHOTO_HINT.search(blob) or _FIGURE_HINT.search(blob):
        return "photo"
    if element is not None and element.element_type is ElementType.IMAGE:
        return "photo"
    return "page"


def _page_context(raw: RawParserResult, page_number: int) -> str:
    parts: list[str] = []
    for element in raw.elements:
        if int(element.page_start) != page_number:
            continue
        if element.element_type not in {
            ElementType.TEXT,
            ElementType.HEADING,
            ElementType.CAPTION,
            ElementType.LIST,
        }:
            continue
        text = (element.normalized_content or element.raw_content or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)[:2_000]


def _page_scanned(raw: RawParserResult, page_number: int) -> bool:
    for page in raw.pages:
        if int(page.page_number) == page_number:
            return bool(page.is_scanned)
    return False


def _page_element_stats(
    raw: RawParserResult,
) -> tuple[dict[int, int], dict[int, float]]:
    densities: dict[int, int] = {}
    image_counts: dict[int, int] = {}
    for element in raw.elements:
        page = int(element.page_start or 1)
        content = (element.normalized_content or element.raw_content or "").strip()
        if content:
            densities[page] = densities.get(page, 0) + len(content)
        if element.element_type in {ElementType.IMAGE, ElementType.CHART, ElementType.DIAGRAM}:
            image_counts[page] = image_counts.get(page, 0) + 1
    coverages: dict[int, float] = {}
    for page, count in image_counts.items():
        density = float(densities.get(page, 0))
        if count >= 1 and density < 400:
            coverages[page] = 0.75 if density < 200 else 0.55
        else:
            coverages[page] = min(1.0, 0.35 + 0.15 * count)
    return densities, coverages


def collect_visual_targets(raw: RawParserResult) -> list[VisualTarget]:
    """Every image/chart/SEM/scan region that should be interpreted."""
    targets: list[VisualTarget] = []
    visual_pages: set[int] = set()
    densities, coverages = _page_element_stats(raw)

    for index, element in enumerate(raw.elements):
        if element.element_type not in {
            ElementType.IMAGE,
            ElementType.CHART,
            ElementType.DIAGRAM,
        }:
            continue
        page_number = int(element.page_start)
        context = _page_context(raw, page_number)
        kind = classify_visual_kind(
            element=element,
            context=context,
            page_is_scanned=_page_scanned(raw, page_number),
        )
        bbox = element.bounding_boxes[0] if element.bounding_boxes else None
        targets.append(
            VisualTarget(
                kind=kind,
                tool=recommended_tool(kind),
                page_number=page_number,
                element_index=index,
                bbox=bbox,
                nearby_text=context,
                reason=f"parser_{element.element_type.value}",
            )
        )
        visual_pages.add(page_number)

    page_texts: dict[int, str] = {}
    for element in raw.elements:
        page = int(element.page_start)
        text = (element.normalized_content or element.raw_content or "").strip()
        if text:
            page_texts[page] = f"{page_texts.get(page, '')}\n{text}".strip()

    for page in raw.pages:
        number = int(page.page_number)
        text = page_texts.get(number, "")
        density = page.text_density
        if density is None:
            density = float(densities.get(number, 0))
        coverage = page.image_coverage
        if coverage is None:
            coverage = coverages.get(number, 0.0)
        scanned = bool(page.is_scanned)
        needs_page = False
        reason = ""
        kind = "page"
        if looks_like_flat_chart_ocr(text):
            needs_page = True
            kind = "chart"
            reason = "flat_chart_ocr"
        elif number not in visual_pages and (
            scanned or (float(coverage or 0) >= 0.5 and float(density or 0) < 200)
        ):
            needs_page = True
            kind = "scan" if scanned or float(density or 0) < 80 else "photo"
            reason = "scanned_or_image_heavy_page"
        if not needs_page:
            continue
        context = _page_context(raw, number) or text[:2_000]
        targets.append(
            VisualTarget(
                kind=kind,
                tool=recommended_tool(kind),
                page_number=number,
                element_index=None,
                bbox=None,
                nearby_text=context,
                reason=reason,
            )
        )

    targets.sort(
        key=lambda item: (
            -KIND_PRIORITY.get(item.kind, 0),
            item.page_number,
            item.element_index if item.element_index is not None else 10_000,
        )
    )
    return targets


VISION_MAX_EDGE = 1280
VISION_RENDER_SCALE = 1.0


def fit_image_for_vision(image: object, *, max_edge: int = VISION_MAX_EDGE) -> object:
    """Downscale a PIL image so vision crops cannot blow the API memory limit."""
    width, height = image.size  # type: ignore[attr-defined]
    longest = max(int(width), int(height))
    if longest <= max_edge or max_edge <= 0:
        return image
    image.thumbnail((max_edge, max_edge))  # type: ignore[attr-defined]
    return image


def render_visual_png(
    data: bytes,
    page_number: int,
    bbox: BoundingBox | None,
    *,
    scale: float = VISION_RENDER_SCALE,
) -> bytes:
    """Render a page or normalized crop as PNG bytes."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        page = document[page_number - 1]
        try:
            bitmap = page.render(scale=scale)
            try:
                pil = bitmap.to_pil()
            finally:
                close = getattr(bitmap, "close", None)
                if callable(close):
                    close()
            if bbox is not None:
                width, height = pil.size
                x0 = int(max(0.0, min(bbox.x0, 1.0)) * width)
                y0 = int(max(0.0, min(bbox.y0, 1.0)) * height)
                x1 = int(max(0.0, min(bbox.x1, 1.0)) * width)
                y1 = int(max(0.0, min(bbox.y1, 1.0)) * height)
                area = max(0, x1 - x0) * max(0, y1 - y0)
                if area >= 64 and area < 0.85 * width * height:
                    pad_x = max(4, int((x1 - x0) * 0.04))
                    pad_y = max(4, int((y1 - y0) * 0.04))
                    pil = pil.crop(
                        (
                            max(0, x0 - pad_x),
                            max(0, y0 - pad_y),
                            min(width, x1 + pad_x),
                            min(height, y1 + pad_y),
                        )
                    )
            pil = fit_image_for_vision(pil)
            if pil.mode not in {"RGB", "L"}:
                pil = pil.convert("RGB")
            buffer = BytesIO()
            pil.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
        finally:
            page.close()
    finally:
        document.close()


def prompt_for_target(target: VisualTarget, page_prompt: str) -> str:
    if target.element_index is None:
        return page_prompt
    return ELEMENT_VISION_PROMPT.format(
        kind=target.kind,
        context=target.nearby_text or "(none)",
    )
