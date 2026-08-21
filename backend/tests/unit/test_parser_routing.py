"""Parser routing unit tests."""

from __future__ import annotations

from enterprise_rag.domain.parsing.routing import AutomaticParserRouter, recommend_from_inspection
from enterprise_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParserProfile,
)


def _inspection(**overrides: object) -> ParserInspection:
    payload: dict[str, object] = {
        "mime_type": "application/pdf",
        "page_count": 3,
        "file_size_bytes": 1024,
        "mean_chars_per_page": 500.0,
        "scanned_page_ratio": 0.0,
        "image_coverage": 0.1,
        "probable_table_density": 0.05,
        "probable_formula_density": 0.05,
        "column_count_estimate": 1,
    }
    payload.update(overrides)
    return ParserInspection(**payload)  # type: ignore[arg-type]


def test_recommend_plain_text() -> None:
    parser, profile, reason = recommend_from_inspection(
        _inspection(mime_type="text/plain"),
        filename="notes.txt",
    )
    assert parser is ParserName.TEXT
    assert profile is ParserProfile.FAST
    assert "text" in reason


def test_recommend_scanned_pdf() -> None:
    parser, profile, _ = recommend_from_inspection(
        _inspection(scanned_page_ratio=0.8, mean_chars_per_page=10.0),
        filename="scan.pdf",
    )
    assert parser is ParserName.PADDLEOCR
    assert profile is ParserProfile.SCANNED


def test_recommend_scientific_pdf() -> None:
    parser, profile, _ = recommend_from_inspection(
        _inspection(probable_formula_density=0.4, mean_chars_per_page=900.0),
        filename="paper.pdf",
    )
    assert parser is ParserName.MINERU
    assert profile is ParserProfile.SCIENTIFIC


def test_recommend_office_docx() -> None:
    parser, profile, _ = recommend_from_inspection(
        _inspection(mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        filename="memo.docx",
    )
    assert parser is ParserName.DOCLING
    assert profile is ParserProfile.BALANCED


def test_router_override() -> None:
    router = AutomaticParserRouter()
    selection = router.select(
        inspection=_inspection(),
        options=ParseOptions(
            parser_override=ParserName.MARKER,
            fallback_parsers=[ParserName.DOCLING],
        ),
        filename="a.pdf",
    )
    assert selection.primary is ParserName.MARKER
    assert selection.fallbacks == [ParserName.DOCLING]
    assert "override" in selection.reason


def test_router_balanced_prefers_inspection_when_disagreeing() -> None:
    router = AutomaticParserRouter()
    selection = router.select(
        inspection=_inspection(scanned_page_ratio=0.9, mean_chars_per_page=5.0),
        options=ParseOptions(profile=ParserProfile.BALANCED),
        filename="scan.pdf",
    )
    assert selection.primary is ParserName.PADDLEOCR
    assert ParserName.PADDLEOCR not in selection.fallbacks


def test_router_explicit_scientific_profile() -> None:
    router = AutomaticParserRouter()
    selection = router.select(
        inspection=_inspection(mean_chars_per_page=400.0),
        options=ParseOptions(profile=ParserProfile.SCIENTIFIC),
        filename="doc.pdf",
    )
    assert selection.profile is ParserProfile.SCIENTIFIC
    assert selection.primary is ParserName.MINERU
