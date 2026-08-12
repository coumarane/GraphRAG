"""Automatic parser routing from inspection metrics and profiles."""

from __future__ import annotations

from dataclasses import dataclass, field

from enterprise_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParserProfile,
    ParserSelection,
)


@dataclass(frozen=True)
class ParserRouteProfile:
    """Primary/fallback chain for a named profile."""

    primary: ParserName
    fallbacks: tuple[ParserName, ...] = ()


DEFAULT_ROUTE_PROFILES: dict[ParserProfile, ParserRouteProfile] = {
    ParserProfile.FAST: ParserRouteProfile(
        primary=ParserName.DOCLING,
        fallbacks=(ParserName.MARKER, ParserName.PDFIUM),
    ),
    ParserProfile.BALANCED: ParserRouteProfile(
        primary=ParserName.DOCLING,
        fallbacks=(
            ParserName.MINERU,
            ParserName.MARKER,
            ParserName.PADDLEOCR,
            ParserName.PDFIUM,
        ),
    ),
    ParserProfile.SCIENTIFIC: ParserRouteProfile(
        primary=ParserName.MINERU,
        fallbacks=(ParserName.DOCLING, ParserName.MARKER, ParserName.PDFIUM),
    ),
    ParserProfile.SCANNED: ParserRouteProfile(
        primary=ParserName.PADDLEOCR,
        fallbacks=(ParserName.MINERU, ParserName.PDFIUM),
    ),
    ParserProfile.ACCURATE: ParserRouteProfile(
        primary=ParserName.MINERU,
        fallbacks=(
            ParserName.DOCLING,
            ParserName.MARKER,
            ParserName.PADDLEOCR,
            ParserName.PDFIUM,
        ),
    ),
}


def _office_or_html(mime_type: str, filename: str) -> bool:
    lowered = filename.lower()
    return (
        mime_type
        in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "text/html",
        }
        or lowered.endswith((".docx", ".pptx", ".html", ".htm"))
    )


def _is_image(mime_type: str) -> bool:
    return mime_type.startswith("image/")


def _is_plain_text(mime_type: str) -> bool:
    return mime_type in {"text/plain", "text/markdown"}


def recommend_from_inspection(
    inspection: ParserInspection,
    *,
    filename: str = "",
) -> tuple[ParserName, ParserProfile, str]:
    """Recommend primary parser and profile from inspection alone."""
    mime = inspection.mime_type.lower()
    if _is_plain_text(mime):
        return ParserName.TEXT, ParserProfile.FAST, "plain text or markdown source"
    if _is_image(mime):
        return ParserName.PADDLEOCR, ParserProfile.SCANNED, "image document requires OCR"
    if _office_or_html(mime, filename):
        return ParserName.DOCLING, ParserProfile.BALANCED, "office/html document"

    if mime == "application/pdf" or mime.endswith("pdf"):
        if inspection.scanned_page_ratio >= 0.6 or inspection.mean_chars_per_page < 40:
            return (
                ParserName.PADDLEOCR,
                ParserProfile.SCANNED,
                "high scanned-page ratio / low text density",
            )
        if (
            inspection.probable_formula_density >= 0.25
            or inspection.probable_table_density >= 0.35
            or (inspection.column_count_estimate or 1) >= 2
        ):
            return (
                ParserName.MINERU,
                ParserProfile.SCIENTIFIC,
                "scientific/complex PDF layout signals",
            )
        return ParserName.DOCLING, ParserProfile.BALANCED, "general text-native PDF"

    return ParserName.DOCLING, ParserProfile.BALANCED, "default enterprise parser"


@dataclass
class AutomaticParserRouter:
    """Select primary/fallback parsers from inspection and profiles."""

    profiles: dict[ParserProfile, ParserRouteProfile] = field(
        default_factory=lambda: dict(DEFAULT_ROUTE_PROFILES)
    )

    def select(
        self,
        *,
        inspection: ParserInspection,
        options: ParseOptions | None = None,
        filename: str = "",
    ) -> ParserSelection:
        opts = options or ParseOptions()
        if opts.parser_override and opts.parser_override is not ParserName.AUTO:
            profile = opts.profile
            fallbacks = list(opts.fallback_parsers) or list(
                self.profiles.get(profile, ParserRouteProfile(opts.parser_override)).fallbacks
            )
            return ParserSelection(
                primary=opts.parser_override,
                fallbacks=[parser for parser in fallbacks if parser != opts.parser_override],
                profile=profile,
                reason=f"explicit parser override: {opts.parser_override.value}",
                inspection=inspection,
            )

        recommended_parser, recommended_profile, reason = recommend_from_inspection(
            inspection,
            filename=filename,
        )

        profile = recommended_profile
        if opts.profile in {
            ParserProfile.SCIENTIFIC,
            ParserProfile.SCANNED,
            ParserProfile.FAST,
            ParserProfile.ACCURATE,
        }:
            profile = opts.profile

        route = self.profiles.get(profile)
        if route is None:
            primary, fallbacks = recommended_parser, []
        else:
            primary = route.primary
            # When inspection strongly disagrees with a balanced profile, prefer recommendation.
            if profile is ParserProfile.BALANCED and recommended_parser != route.primary:
                primary = recommended_parser
            fallbacks = [parser for parser in route.fallbacks if parser != primary]

        return ParserSelection(
            primary=primary,
            fallbacks=fallbacks,
            profile=profile,
            reason=reason,
            inspection=inspection,
        )
