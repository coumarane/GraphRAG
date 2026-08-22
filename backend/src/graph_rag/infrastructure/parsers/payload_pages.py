"""Shared page-metric helpers for parser convert payloads."""

from __future__ import annotations

from typing import Any


def build_pages_from_elements(
    elements: list[dict[str, Any]],
    *,
    page_count: int,
) -> list[dict[str, Any]]:
    """Derive text density / image coverage hints used by vision page selection."""
    text_chars: dict[int, int] = {}
    image_counts: dict[int, int] = {}
    for item in elements:
        page = int(item.get("page", 1) or 1)
        text = str(item.get("text") or "")
        if text:
            text_chars[page] = text_chars.get(page, 0) + len(text)
        if str(item.get("type") or "").lower() in {
            "image",
            "chart",
            "picture",
            "figure",
            "diagram",
        }:
            image_counts[page] = image_counts.get(page, 0) + 1

    pages: list[dict[str, Any]] = []
    for number in range(1, max(page_count, 1) + 1):
        density = float(text_chars.get(number, 0))
        images = image_counts.get(number, 0)
        if images >= 1 and density < 400:
            coverage = 0.75 if density < 200 else 0.55
        elif images >= 1:
            coverage = min(1.0, 0.35 + 0.15 * images)
        else:
            coverage = 0.0
        pages.append(
            {
                "page_number": number,
                "text_density": density,
                "image_coverage": coverage,
            }
        )
    return pages
