"""Parser plugin injection and seventh-parser discovery tests (Phase 1)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from graph_rag.application.ingestion.local_pipeline import _parse_document_raw
from graph_rag.application.plugins.descriptors import PluginDescriptor
from graph_rag.application.plugins.parsers import (
    resolve_inspector_name,
    validate_parsing_profile_primaries,
)
from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParseSource,
    RawElement,
    RawParserResult,
    parser_key,
)
from graph_rag.infrastructure.parsers.registry import ParseDocumentService, ParserRegistry
from graph_rag.shared.exceptions import ConfigurationError, ParserError


class _EchoParser:
    name = "echo"

    async def inspect(self, source: ParseSource) -> ParserInspection:
        return ParserInspection(
            mime_type=source.mime_type,
            page_count=1,
            file_size_bytes=len(source.require_bytes()),
            recommended_parser="echo",
        )

    async def parse(self, source: ParseSource, options: ParseOptions) -> RawParserResult:
        text = source.require_bytes().decode("utf-8", errors="replace")
        return RawParserResult(
            parser_name="echo",
            page_count=1,
            elements=[
                RawElement(
                    element_type=ElementType.TEXT,
                    page_start=1,
                    page_end=1,
                    reading_order=0,
                    raw_content=text,
                    normalized_content=text,
                )
            ],
            metadata={"echo": text},
        )


def test_inspector_prefers_docling_when_registered() -> None:
    assert resolve_inspector_name(["pdfium", "docling", "text"]) == "docling"


def test_inspector_defaults_to_pdfium_without_docling() -> None:
    assert resolve_inspector_name(["pdfium", "text"]) == "pdfium"


def test_configured_inspector_missing_raises() -> None:
    with pytest.raises(ConfigurationError, match="inspector is not registered"):
        resolve_inspector_name(["pdfium"], configured="missing")


def test_profile_primary_must_be_registered() -> None:
    with pytest.raises(ConfigurationError, match="primary is not registered"):
        validate_parsing_profile_primaries(
            {"balanced": SimpleNamespace(primary="not-a-parser")},
            ["docling", "pdfium"],
        )


@pytest.mark.asyncio
async def test_inspect_uses_pdfium_when_docling_absent() -> None:
    from graph_rag.infrastructure.parsers.pdfium import PdfiumParser
    from graph_rag.infrastructure.parsers.text import TextDocumentParser

    registry = ParserRegistry(
        parsers={
            "pdfium": PdfiumParser(),
            "text": TextDocumentParser(),
        }
    )
    service = ParseDocumentService(registry=registry)
    assert service._inspector_name == "pdfium"
    source = ParseSource(
        tenant_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        filename="notes.txt",
        mime_type="text/plain",
        content=b"hello",
    )
    inspection = await service.inspect(source)
    assert inspection.mime_type == "text/plain"


@pytest.mark.asyncio
async def test_seventh_parser_selectable_without_parsername_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = PluginDescriptor(
        plugin_name="echo",
        capability="parser",
        trust_tier="community",
        builder=lambda _settings: _EchoParser(),
        structured=True,
    )

    class _Entry:
        name = "echo"

        def load(self) -> PluginDescriptor:
            return descriptor

    from graph_rag.application.plugins.discovery import clear_entry_point_cache
    from graph_rag.infrastructure.parsers.registry import parser_registry_from_settings

    clear_entry_point_cache()
    monkeypatch.setattr(
        "graph_rag.application.plugins.discovery.load_entry_points",
        lambda group: (_Entry(),) if group == "graph_rag.parser" else (),
    )
    registry = parser_registry_from_settings(None)
    assert "echo" in registry.names()
    service = ParseDocumentService(registry=registry, inspector_name="pdfium")
    source = ParseSource(
        tenant_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        filename="note.txt",
        mime_type="text/plain",
        content=b"hello plugin",
    )
    raw = await service.parse_raw(source, "echo", ParseOptions(parser_override="echo"))
    assert raw.parser_name == "echo"
    assert parser_key("echo") == "echo"
    assert "echo" not in {member.value for member in ParserName}

    outcome = await _parse_document_raw(
        data=b"hello plugin",
        filename="note.txt",
        mime_type="text/plain",
        tenant_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        parser_requested="echo",
        max_pages=2,
        parse_service=service,
    )
    assert outcome.used_parser == "echo"
    assert outcome.selected_parser == "echo"


@pytest.mark.asyncio
async def test_unknown_parser_name_raises() -> None:
    service = ParseDocumentService(
        registry=ParserRegistry(parsers={"pdfium": _EchoParser()}),  # type: ignore[dict-item]
        inspector_name="pdfium",
    )
    source = ParseSource(
        tenant_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        filename="a.txt",
        mime_type="text/plain",
        content=b"x",
    )
    with pytest.raises(ParserError, match="not registered"):
        await service.parse_raw(source, "nope")
