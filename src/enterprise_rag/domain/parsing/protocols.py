"""Application-owned parser provider protocols."""

from __future__ import annotations

from typing import Protocol

from enterprise_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParseSource,
    RawParserResult,
)


class DocumentInspector(Protocol):
    """Inspect a document before parser selection."""

    @property
    def name(self) -> str:
        """Inspector name."""
        ...

    async def inspect(self, source: ParseSource) -> ParserInspection:
        """Return routing metrics for the source document."""
        ...


class MultimodalDocumentParser(Protocol):
    """Parser adapter protocol. Adapters must not write to databases."""

    @property
    def name(self) -> str:
        """Stable parser name used in routing and provenance."""
        ...

    async def inspect(self, source: ParseSource) -> ParserInspection:
        """Inspect the source (may delegate to PDFium)."""
        ...

    async def parse(
        self,
        source: ParseSource,
        options: ParseOptions,
    ) -> RawParserResult:
        """Parse into a raw intermediate representation."""
        ...
