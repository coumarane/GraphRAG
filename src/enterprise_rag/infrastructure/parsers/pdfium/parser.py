"""pypdfium2 multimodal parser adapter (always-available fallback)."""

from __future__ import annotations

from enterprise_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParseSource,
    RawParserResult,
)
from enterprise_rag.infrastructure.parsers.pdfium.extractor import extract_pdf_raw, extract_text_raw
from enterprise_rag.infrastructure.parsers.pdfium.inspector import PdfiumInspector
from enterprise_rag.shared.exceptions import ValidationError


class PdfiumParser:
    """Reliable text extraction fallback when heavier parsers are unavailable."""

    name = ParserName.PDFIUM.value

    def __init__(
        self,
        inspector: PdfiumInspector | None = None,
        *,
        max_pages: int = 2_000,
    ) -> None:
        self._inspector = inspector or PdfiumInspector()
        self._max_pages = max_pages

    async def inspect(self, source: ParseSource) -> ParserInspection:
        return await self._inspector.inspect(source)

    async def parse(self, source: ParseSource, options: ParseOptions) -> RawParserResult:
        data = source.require_bytes()
        mime = (source.mime_type or "").lower()
        filename = source.filename
        if mime == "application/pdf" or filename.lower().endswith(".pdf"):
            return extract_pdf_raw(data, filename=filename, max_pages=self._max_pages)
        if mime.startswith("text/") or filename.lower().endswith(
            (".txt", ".md", ".markdown", ".csv")
        ):
            return extract_text_raw(data, filename=filename)
        raise ValidationError(
            "Pdfium parser supports PDF and plain text only",
            details={"mime_type": mime, "filename": filename},
        )
