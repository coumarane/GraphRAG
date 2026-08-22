"""Built-in plain-text / markdown / HTML parser (no heavy SDK)."""

from __future__ import annotations

from html.parser import HTMLParser

from graph_rag.domain.elements.enums import ElementType
from graph_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParseSource,
    RawElement,
    RawPage,
    RawParserResult,
)
from graph_rag.domain.types import JsonValue
from graph_rag.infrastructure.parsers.pdfium.inspector import PdfiumInspector


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self.chunks.append(text)


class TextDocumentParser:
    """Parse text, markdown and simple HTML into raw elements."""

    name = ParserName.TEXT.value

    def __init__(self, inspector: PdfiumInspector | None = None) -> None:
        self._inspector = inspector or PdfiumInspector()

    async def inspect(self, source: ParseSource) -> ParserInspection:
        return await self._inspector.inspect(source)

    async def parse(self, source: ParseSource, options: ParseOptions) -> RawParserResult:
        data = source.require_bytes()
        text = data.decode("utf-8", errors="replace")
        if source.mime_type == "text/html" or source.filename.lower().endswith((".html", ".htm")):
            extractor = _HTMLTextExtractor()
            extractor.feed(text)
            text = " ".join(extractor.chunks)

        blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
        if not blocks and text.strip():
            blocks = [text.strip()]

        elements: list[RawElement] = []
        for index, block in enumerate(blocks):
            element_type = ElementType.TEXT
            metadata: dict[str, JsonValue] = {}
            if source.mime_type == "text/markdown" and block.lstrip().startswith("#"):
                element_type = ElementType.HEADING
                hashes = len(block) - len(block.lstrip("#"))
                metadata["level"] = max(1, min(hashes, 9))
                block = block.lstrip("#").strip()
            elements.append(
                RawElement(
                    element_type=element_type,
                    page_start=1,
                    page_end=1,
                    reading_order=index,
                    raw_content=block,
                    normalized_content=block,
                    metadata=metadata,
                )
            )

        return RawParserResult(
            parser_name=self.name,
            parser_version="builtin-1",
            title=source.filename,
            page_count=1,
            pages=[RawPage(page_number=1, text_density=float(len(text)))],
            elements=elements,
            warnings=[],
        )
