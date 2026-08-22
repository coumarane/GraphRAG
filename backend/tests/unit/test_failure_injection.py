"""Parser / storage failure-injection regression tests."""

from __future__ import annotations

import pytest

from graph_rag.domain.parsing.types import ParseOptions, ParserName, ParseSource
from graph_rag.infrastructure.parsers.registry import ParseDocumentService, ParserRegistry
from graph_rag.shared.exceptions import ParserError
from graph_rag.domain.ids import new_id


class _FailingParser:
    name = ParserName.DOCLING.value

    async def inspect(self, source: ParseSource):  # noqa: ANN201
        raise ParserError("forced inspect failure")

    async def parse(self, source: ParseSource, options: ParseOptions):  # noqa: ANN201
        raise ParserError("forced parse failure")


@pytest.mark.asyncio
async def test_parse_service_fails_loudly_when_all_parsers_fail() -> None:
    registry = ParserRegistry(
        parsers={ParserName.DOCLING.value: _FailingParser()},  # type: ignore[dict-item]
    )
    service = ParseDocumentService(registry=registry)
    source = ParseSource(
        tenant_id=new_id(),
        document_id=new_id(),
        version_id=new_id(),
        filename="broken.pdf",
        mime_type="application/pdf",
        content=b"%PDF-1.4 empty",
    )
    with pytest.raises(ParserError) as exc:
        await service.parse(
            source,
            ParseOptions(parser_override=ParserName.DOCLING, failure_mode="fail_fast"),
        )
    # Must not silently succeed with an empty document.
    assert str(exc.value)
