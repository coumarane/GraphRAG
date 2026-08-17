"""Regression: live ingest uses parser registry with pdfium fallback."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from enterprise_rag.application.ingestion.local_pipeline import _parse_document_raw
from enterprise_rag.domain.parsing.types import ParseOptions, ParserName, ParseSource
from enterprise_rag.infrastructure.parsers.pdfium import PdfiumParser
from enterprise_rag.infrastructure.parsers.registry import ParseDocumentService, ParserRegistry


@pytest.mark.asyncio
async def test_parse_document_raw_uses_registry_with_available_parser() -> None:
    sample = Path("examples/sample.pdf")
    if not sample.exists():
        pytest.skip("examples/sample.pdf missing")
    data = sample.read_bytes()
    outcome = await _parse_document_raw(
        data=data,
        filename=sample.name,
        mime_type="application/pdf",
        tenant_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        parser_requested="auto",
        max_pages=5,
    )
    raw, attempted = outcome.raw, outcome.attempted
    assert outcome.attempts
    assert outcome.selected_parser
    assert outcome.used_parser == raw.parser_name
    assert raw.elements
    assert raw.page_count >= 1
    assert attempted
    # Prefer Docling when installed; otherwise pdfium fallback must appear.
    assert raw.parser_name in {"docling", "pdfium", "pdfium_multimodal"} or any(
        name in {"docling", "pdfium"} for name in attempted
    )


@pytest.mark.asyncio
async def test_registry_includes_pdfium_parser() -> None:
    registry = ParserRegistry()
    assert ParserName.PDFIUM.value in registry.names()
    parser = registry.get(ParserName.PDFIUM)
    assert isinstance(parser, PdfiumParser)


@pytest.mark.asyncio
async def test_explicit_pdfium_override_parses_sample() -> None:
    sample = Path("examples/sample.pdf")
    if not sample.exists():
        pytest.skip("examples/sample.pdf missing")
    source = ParseSource(
        tenant_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        filename=sample.name,
        mime_type="application/pdf",
        content=sample.read_bytes(),
    )
    service = ParseDocumentService()
    raw = await service.parse_raw(
        source,
        ParserName.PDFIUM,
        ParseOptions(parser_override=ParserName.PDFIUM),
    )
    assert raw.parser_name == "pdfium"
    assert raw.elements
