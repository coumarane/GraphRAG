"""Docling adapter must convert per-item provenance geometry into our bbox format.

Regression coverage for a gap where the adapter read ``item.prov`` only to
recover a page number and discarded the ``bbox`` sitting right next to it --
so every parsed element (text, headings, tables, images alike) came out with
no geometry at all, not just vision-enriched ones. Docling's own bbox is in
PDF-point units and, empirically, uses a bottom-left coordinate origin; these
tests exercise the real ``docling_core`` bbox type (not a hand-rolled fake)
so the ``to_top_left_origin`` conversion this adapter relies on is exercised
against the actual library behavior.
"""

from __future__ import annotations

from types import SimpleNamespace

from docling_core.types.doc.base import BoundingBox as DoclingBoundingBox
from docling_core.types.doc.base import CoordOrigin

from graph_rag.infrastructure.parsers.docling.adapter import _bbox_from_item, _page_size


def _page_document(width: float, height: float) -> SimpleNamespace:
    return SimpleNamespace(
        pages={1: SimpleNamespace(size=SimpleNamespace(width=width, height=height))}
    )


def _item_with_bbox(bbox: DoclingBoundingBox, page_no: int = 1) -> SimpleNamespace:
    return SimpleNamespace(prov=[SimpleNamespace(bbox=bbox, page_no=page_no)])


def test_page_size_reads_width_and_height_from_document_pages() -> None:
    document = _page_document(612.0, 792.0)
    assert _page_size(document, 1) == (612.0, 792.0)


def test_page_size_returns_none_for_missing_page() -> None:
    document = _page_document(612.0, 792.0)
    assert _page_size(document, 2) is None


def test_bbox_from_item_converts_bottom_left_origin_to_normalized_top_left() -> None:
    # A region in the upper-left area of a 612x792 page, in Docling's own
    # (empirically confirmed) bottom-left-origin point units.
    docling_bbox = DoclingBoundingBox(
        l=61.2, t=752.4, r=306.0, b=712.8, coord_origin=CoordOrigin.BOTTOMLEFT
    )
    item = _item_with_bbox(docling_bbox)

    result = _bbox_from_item(item, page_no=1, page_size=(612.0, 792.0))

    assert result is not None
    assert result["page_number"] == 1
    assert result["x0"] == 0.1
    assert result["x1"] == 0.5
    # Bottom-left t=752.4 -> top-left top = 792 - 752.4 = 39.6 -> /792 = 0.05
    assert round(result["y0"], 6) == 0.05
    # Bottom-left b=712.8 -> top-left bottom = 792 - 712.8 = 79.2 -> /792 = 0.1
    assert round(result["y1"], 6) == 0.1


def test_bbox_from_item_returns_none_without_prov() -> None:
    item = SimpleNamespace(prov=[])
    assert _bbox_from_item(item, page_no=1, page_size=(612.0, 792.0)) is None


def test_bbox_from_item_returns_none_without_page_size() -> None:
    docling_bbox = DoclingBoundingBox(l=0, t=100, r=50, b=50, coord_origin=CoordOrigin.BOTTOMLEFT)
    item = _item_with_bbox(docling_bbox)
    assert _bbox_from_item(item, page_no=1, page_size=None) is None


def test_bbox_from_item_returns_none_for_degenerate_box() -> None:
    # A zero-width box (l == r) would otherwise pass through as a
    # zero-area highlight the frontend can never click.
    docling_bbox = DoclingBoundingBox(
        l=100, t=200, r=100, b=100, coord_origin=CoordOrigin.BOTTOMLEFT
    )
    item = _item_with_bbox(docling_bbox)
    assert _bbox_from_item(item, page_no=1, page_size=(612.0, 792.0)) is None
