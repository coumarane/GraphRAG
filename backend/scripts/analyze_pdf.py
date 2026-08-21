#!/usr/bin/env python3
"""PDF forensics utility for parser routing and corpus inventory.

Usage:
  uv run python scripts/analyze_pdf.py path/to/document.pdf
  uv run python scripts/analyze_pdf.py sample_data --recursive
  uv run python scripts/analyze_pdf.py sample_data --recursive --compare-parsers
  uv run python scripts/analyze_pdf.py ../data/samples --recursive --json-out ../data/reports/corpus-inventory.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from enterprise_rag.domain.parsing.routing import recommend_from_inspection
from enterprise_rag.domain.parsing.types import ParseSource, ParserName
from enterprise_rag.infrastructure.parsers.pdfium.inspector import PdfiumInspector

_TABLE_RE = re.compile(
    r"(?i)\b(inci|cas|specification|item|unit|value|density|viscosity|"
    r"particle\s*size|surface\s*area|content\s*\(%\)|wt\s*%|ppm)\b"
)
_EQUATION_RE = re.compile(
    r"(η|tau|gamma|μ|µm|μm|Al2O3|SiO2|TiO2|C\d{2}|H\d{2}|"
    r"[=≈≤≥→∑∫√]|_\d|\^\d|×\s*10)"
)
_HEADER_FOOTER_CANDIDATES = re.compile(
    r"(?i)^(confidential|copyright|©|page\s+\d+|rev(ision)?\s*[:.]|"
    r"all rights reserved|proprietary|document\s*id)"
)
_LANG_HINTS = {
    "ja": re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]"),
    "ko": re.compile(r"[\uac00-\ud7af]"),
    "zh": re.compile(r"[\u4e00-\u9fff]"),
    "fr": re.compile(r"\b(le|la|les|des|une|pour|avec)\b", re.I),
}


def _classify_document(
    *,
    filename: str,
    pages: int,
    scanned_ratio: float,
    mean_chars: float,
    table_hits: int,
    equation_hits: int,
    image_pages: int,
) -> list[str]:
    labels: list[str] = []
    lowered = filename.lower()
    if scanned_ratio >= 0.6 or mean_chars < 40:
        labels.append("SCANNED")
    elif scanned_ratio > 0.15:
        labels.append("MIXED")
    else:
        labels.append("TEXT_NATIVE")
    if equation_hits >= 3 or "equation" in lowered:
        labels.append("FORMULA_HEAVY")
        labels.append("SCIENTIFIC")
    if table_hits >= 5 or "tds" in lowered or "spec" in lowered:
        labels.append("TABLE_HEAVY")
        labels.append("TECHNICAL_DATASHEET")
    if image_pages >= max(2, pages // 3):
        labels.append("IMAGE_HEAVY")
    if "sds" in lowered or "safety" in lowered:
        labels.append("SDS")
    if "presentation" in lowered or pages >= 20 and mean_chars < 600:
        labels.append("PRESENTATION_STYLE")
    if "catalog" in lowered or "lineup" in lowered:
        labels.append("PRODUCT_SPECIFICATION")
    if "leaflet" in lowered or "brochure" in lowered or "flyer" in lowered:
        labels.append("MARKETING")
    if not labels:
        labels.append("UNKNOWN")
    # Preserve order, unique.
    seen: set[str] = set()
    ordered: list[str] = []
    for label in labels:
        if label not in seen:
            seen.add(label)
            ordered.append(label)
    return ordered


def _detect_languages(text: str) -> list[str]:
    if not text.strip():
        return []
    found: list[str] = []
    for code, pattern in _LANG_HINTS.items():
        if pattern.search(text):
            found.append(code)
    ascii_letters = sum(1 for ch in text if "a" <= ch.lower() <= "z")
    if ascii_letters > 40 and "en" not in found:
        found.insert(0, "en")
    return found or ["und"]


def _analyze_pdfium_rich(data: bytes) -> dict[str, Any]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        page_count = len(document)
        text_native = 0
        scanned = 0
        images = 0
        tables = 0
        equations = 0
        multi_column = 0
        headers = False
        footers = False
        page_texts: list[str] = []
        top_lines: list[str] = []
        bottom_lines: list[str] = []
        for index in range(page_count):
            page = document[index]
            width, height = page.get_size()
            text_page = page.get_textpage()
            try:
                text = text_page.get_text_bounded() or ""
            finally:
                text_page.close()
            # Image object count when available.
            try:
                image_count = len(page.get_objects(filter=pdfium.raw.FPDF_PAGEOBJ_IMAGE))
            except Exception:
                image_count = 0
            page.close()
            stripped = text.strip()
            page_texts.append(stripped)
            char_count = len(stripped)
            if char_count < 40:
                scanned += 1
            else:
                text_native += 1
            if image_count > 0 or char_count < 40:
                images += image_count or 1
            table_hits = len(_TABLE_RE.findall(stripped))
            equation_hits = len(_EQUATION_RE.findall(stripped))
            tables += 1 if table_hits >= 2 else 0
            equations += equation_hits
            lines = [line.strip() for line in stripped.splitlines() if line.strip()]
            if lines:
                top_lines.append(lines[0][:120])
                bottom_lines.append(lines[-1][:120])
                if _HEADER_FOOTER_CANDIDATES.search(lines[0]):
                    headers = True
                if _HEADER_FOOTER_CANDIDATES.search(lines[-1]) or re.search(
                    r"\b\d+\s*/\s*\d+\b|\bpage\s+\d+\b", lines[-1], re.I
                ):
                    footers = True
            # Crude multi-column: high char density on landscape-ish pages.
            if width > height and char_count > 800:
                multi_column += 1
            elif char_count > 1600 and width / max(height, 1.0) > 0.7:
                multi_column += 1

        # Header/footer repetition via frequency.
        if page_count >= 3:
            top_counts = Counter(top_lines)
            bottom_counts = Counter(bottom_lines)
            if top_counts and top_counts.most_common(1)[0][1] / page_count >= 0.5:
                headers = True
            if bottom_counts and bottom_counts.most_common(1)[0][1] / page_count >= 0.5:
                footers = True

        joined = "\n".join(page_texts)
        return {
            "pages": page_count,
            "text_native_pages": text_native,
            "scanned_pages": scanned,
            "images": images,
            "tables": tables,
            "equations": equations,
            "headers_detected": headers,
            "footers_detected": footers,
            "multi_column_pages": multi_column,
            "languages": _detect_languages(joined[:8000]),
            "mean_chars_per_page": (sum(len(t) for t in page_texts) / page_count)
            if page_count
            else 0.0,
            "sample_text": joined[:500],
        }
    finally:
        document.close()


def _parser_available(name: str) -> bool:
    module_map = {
        "docling": ("docling",),
        "mineru": ("mineru", "magic_pdf"),
        "marker": ("marker",),
        "paddleocr": ("paddleocr",),
        "pdfium": ("pypdfium2",),
    }
    modules = module_map.get(name)
    if not modules:
        return False
    for module in modules:
        try:
            __import__(module)
            return True
        except Exception:
            continue
    return False


async def _try_parser_compare(path: Path, data: bytes) -> dict[str, Any]:
    """Best-effort parser comparison; mark unavailable parsers as NEEDS_REVIEW."""
    from enterprise_rag.infrastructure.parsers.registry import ParseDocumentService

    results: dict[str, Any] = {}
    service = ParseDocumentService()
    source = ParseSource(
        tenant_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        filename=path.name,
        mime_type="application/pdf",
        content=data,
    )
    for parser_name in (
        ParserName.DOCLING,
        ParserName.MINERU,
        ParserName.MARKER,
        ParserName.PADDLEOCR,
    ):
        key = parser_name.value
        if not _parser_available(key):
            results[key] = {
                "status": "NEEDS_REVIEW",
                "reason": f"optional dependency for {key} is not installed",
            }
            continue
        started = time.perf_counter()
        try:
            from enterprise_rag.domain.parsing.types import ParseOptions

            raw = await service.parse_raw(
                source,
                parser_name,
                ParseOptions(parser_override=parser_name),
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            results[key] = {
                "status": "ok",
                "elements": len(raw.elements),
                "pages": raw.page_count,
                "warnings": raw.warnings,
                "latency_ms": round(elapsed_ms, 1),
                "text_accuracy": "NEEDS_REVIEW",
                "reading_order": "NEEDS_REVIEW",
                "tables": "NEEDS_REVIEW",
                "equations": "NEEDS_REVIEW",
                "images": "NEEDS_REVIEW",
                "scanned_pages": "NEEDS_REVIEW",
            }
        except Exception as exc:
            results[key] = {
                "status": "failed",
                "error": str(exc)[:300],
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
            }
    # Always include pdfium baseline metrics.
    started = time.perf_counter()
    rich = _analyze_pdfium_rich(data)
    results["pdfium"] = {
        "status": "ok",
        "pages": rich["pages"],
        "text_native_pages": rich["text_native_pages"],
        "scanned_pages": rich["scanned_pages"],
        "tables": rich["tables"],
        "equations": rich["equations"],
        "images": rich["images"],
        "latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "text_accuracy": "NEEDS_REVIEW",
        "reading_order": "NEEDS_REVIEW",
    }
    return results


async def analyze_one(
    path: Path,
    *,
    compare_parsers: bool = False,
) -> dict[str, Any]:
    data = path.read_bytes()
    inspector = PdfiumInspector()
    source = ParseSource(
        tenant_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        filename=path.name,
        mime_type="application/pdf",
        content=data,
    )
    inspection = await inspector.inspect(source)
    parser, profile, reason = recommend_from_inspection(inspection, filename=path.name)
    rich = _analyze_pdfium_rich(data)
    confidence = 0.55
    if inspection.scanned_page_ratio >= 0.6:
        confidence = 0.9
    elif inspection.probable_formula_density >= 0.25:
        confidence = 0.8
    elif inspection.mean_chars_per_page > 200:
        confidence = 0.75

    labels = _classify_document(
        filename=path.name,
        pages=rich["pages"],
        scanned_ratio=inspection.scanned_page_ratio,
        mean_chars=float(rich["mean_chars_per_page"]),
        table_hits=int(rich["tables"]),
        equation_hits=int(rich["equations"]),
        image_pages=int(rich["scanned_pages"]),
    )
    payload: dict[str, Any] = {
        "filename": path.name,
        "path": str(path),
        "file_size": len(data),
        "pages": rich["pages"],
        "text_native_pages": rich["text_native_pages"],
        "scanned_pages": rich["scanned_pages"],
        "images": rich["images"],
        "tables": rich["tables"],
        "equations": rich["equations"],
        "headers_detected": rich["headers_detected"],
        "footers_detected": rich["footers_detected"],
        "multi_column_pages": rich["multi_column_pages"],
        "languages": rich["languages"],
        "mean_chars_per_page": round(float(rich["mean_chars_per_page"]), 1),
        "scanned_page_ratio": round(inspection.scanned_page_ratio, 3),
        "parser_recommendation": parser.value,
        "parser_profile": profile.value,
        "parser_confidence": confidence,
        "parser_reason": reason,
        "classification": labels,
        "pdf_type": labels[0] if labels else "UNKNOWN",
        "layout_complexity": (
            "high"
            if rich["multi_column_pages"] or rich["tables"] >= 3 or rich["pages"] > 40
            else "medium"
            if rich["pages"] > 10 or rich["tables"]
            else "low"
        ),
        "parser_candidates": [parser.value, *[p.value for p in (
            # rough candidates for operators
        )]],
    }
    # Candidate list from profile defaults.
    from enterprise_rag.domain.parsing.routing import DEFAULT_ROUTE_PROFILES

    route = DEFAULT_ROUTE_PROFILES.get(profile)
    if route:
        payload["parser_candidates"] = [route.primary.value, *[p.value for p in route.fallbacks]]
    if compare_parsers:
        payload["parser_comparison"] = await _try_parser_compare(path, data)
    return payload


def _collect_pdfs(target: Path, *, recursive: bool) -> list[Path]:
    if target.is_file():
        return [target]
    pattern = "**/*" if recursive else "*"
    paths = sorted(
        {
            *target.glob(f"{pattern}.pdf"),
            *target.glob(f"{pattern}.PDF"),
        }
    )
    return [path for path in paths if path.is_file()]


async def _amain(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.exists():
        print(f"Path not found: {target}", file=sys.stderr)
        return 1
    pdfs = _collect_pdfs(target, recursive=args.recursive)
    if not pdfs:
        print("No PDF files found.", file=sys.stderr)
        return 1
    reports: list[dict[str, Any]] = []
    for path in pdfs:
        report = await analyze_one(path, compare_parsers=args.compare_parsers)
        reports.append(report)
        if not args.quiet:
            print(json.dumps(report, ensure_ascii=False, indent=2 if len(pdfs) == 1 else None))
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {len(reports)} reports to {out}", file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze PDFs for RAG parser routing")
    parser.add_argument("path", help="PDF file or directory")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--compare-parsers", action="store_true")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
