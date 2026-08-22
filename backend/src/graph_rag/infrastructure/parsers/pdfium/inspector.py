"""pypdfium2-based PDF inspection and text-density estimation."""

from __future__ import annotations

import asyncio

from graph_rag.domain.parsing.routing import recommend_from_inspection
from graph_rag.domain.parsing.types import (
    PageInspection,
    ParserInspection,
    ParserName,
    ParserProfile,
    ParseSource,
)
from graph_rag.domain.storage.limits import assert_within_page_limit
from graph_rag.infrastructure.intake.mime_detection import detect_mime_type
from graph_rag.shared.exceptions import ParserError, UnsupportedDocumentError, ValidationError


class PdfiumInspector:
    """Inspect PDFs for routing. Not a primary semantic parser."""

    name = ParserName.PDFIUM.value

    def __init__(
        self,
        *,
        scanned_char_threshold: int = 40,
        max_pages: int = 2_000,
    ) -> None:
        self._scanned_char_threshold = scanned_char_threshold
        self._max_pages = max_pages

    async def inspect(self, source: ParseSource) -> ParserInspection:
        data = source.require_bytes()
        mime = source.mime_type or detect_mime_type(data, filename=source.filename)
        if mime != "application/pdf" and not source.filename.lower().endswith(".pdf"):
            is_text = mime.startswith("text/")
            is_image = mime.startswith("image/")
            text_len = len(data.decode("utf-8", errors="ignore")) if is_text else 0
            return ParserInspection(
                mime_type=mime,
                page_count=1 if data else 0,
                file_size_bytes=len(data),
                pages=[],
                extractable_chars_per_page=[text_len] if is_text else [],
                mean_chars_per_page=float(text_len) if is_text else 0.0,
                scanned_page_ratio=1.0 if is_image else 0.0,
                image_coverage=1.0 if is_image else 0.0,
                recommended_profile=(
                    ParserProfile.SCANNED if is_image else ParserProfile.BALANCED
                ),
                recommended_parser=(
                    ParserName.PADDLEOCR if is_image else ParserName.DOCLING
                ),
            )

        try:
            inspection = await asyncio.to_thread(self._inspect_pdf, data, mime)
        except (UnsupportedDocumentError, ValidationError):
            raise
        except Exception as exc:
            raise ParserError("PDFium inspection failed", cause=exc) from exc

        parser, profile, _reason = recommend_from_inspection(
            inspection,
            filename=source.filename,
        )
        return inspection.model_copy(
            update={
                "recommended_parser": parser,
                "recommended_profile": profile,
            }
        )

    def _inspect_pdf(self, data: bytes, mime: str) -> ParserInspection:
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:
            from graph_rag.shared.exceptions import ConfigurationError

            raise ConfigurationError(
                "pypdfium2 is required for PDF inspection",
                cause=exc,
            ) from exc

        try:
            document = pdfium.PdfDocument(data)
        except Exception as exc:
            raise UnsupportedDocumentError("Unable to open PDF with pypdfium2", cause=exc) from exc

        try:
            pages: list[PageInspection] = []
            chars: list[int] = []
            image_coverages: list[float] = []
            for index in range(len(document)):
                page = document[index]
                width, height = page.get_size()
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_bounded() or ""
                finally:
                    text_page.close()
                char_count = len(text.strip())
                # Heuristic image coverage: pages with almost no text are treated as image-heavy.
                coverage = 0.9 if char_count < self._scanned_char_threshold else 0.1
                scanned = char_count < self._scanned_char_threshold
                pages.append(
                    PageInspection(
                        page_number=index + 1,
                        width=float(width),
                        height=float(height),
                        extractable_chars=char_count,
                        image_coverage=coverage,
                        is_scanned_candidate=scanned,
                    )
                )
                chars.append(char_count)
                image_coverages.append(coverage)
                page.close()
        finally:
            document.close()

        page_count = len(pages)
        assert_within_page_limit(page_count, max_pages=self._max_pages)
        scanned_ratio = 0.0
        if page_count:
            scanned_ratio = (
                sum(1 for page in pages if page.is_scanned_candidate) / page_count
            )
        mean_chars = (sum(chars) / page_count) if page_count else 0.0
        mean_image = (sum(image_coverages) / page_count) if page_count else 0.0
        # Lightweight heuristics until layout classifiers exist.
        formula_density = 0.3 if mean_chars > 800 and scanned_ratio < 0.2 else 0.05
        table_density = 0.2 if mean_chars > 500 else 0.05
        columns = 2 if mean_chars > 1200 and scanned_ratio < 0.2 else 1

        return ParserInspection(
            mime_type=mime,
            page_count=page_count,
            file_size_bytes=len(data),
            pages=pages,
            extractable_chars_per_page=chars,
            mean_chars_per_page=mean_chars,
            scanned_page_ratio=scanned_ratio,
            image_coverage=mean_image,
            probable_table_density=table_density,
            probable_formula_density=formula_density,
            column_count_estimate=columns,
            warnings=[],
            metadata={"inspector": self.name},
        )
