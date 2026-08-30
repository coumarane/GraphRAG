"""Automatic parser routing from inspection metrics and profiles."""

from __future__ import annotations

from dataclasses import dataclass, field

from graph_rag.domain.parsing.types import (
    ParseOptions,
    ParserInspection,
    ParserName,
    ParserProfile,
    ParserSelection,
    parser_key,
)


@dataclass(frozen=True)
class ParserRouteProfile:
    """Primary/fallback chain for a named profile."""

    primary: ParserName | str
    fallbacks: tuple[ParserName | str, ...] = ()


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
) -> tuple[str, ParserProfile, str]:
    """Recommend primary parser and profile from inspection alone."""
    mime = inspection.mime_type.lower()
    if _is_plain_text(mime):
        return ParserName.TEXT.value, ParserProfile.FAST, "plain text or markdown source"
    if _is_image(mime):
        return ParserName.PADDLEOCR.value, ParserProfile.SCANNED, "image document requires OCR"
    if _office_or_html(mime, filename):
        return ParserName.DOCLING.value, ParserProfile.BALANCED, "office/html document"

    if mime == "application/pdf" or mime.endswith("pdf"):
        if inspection.scanned_page_ratio >= 0.6 or inspection.mean_chars_per_page < 40:
            return (
                ParserName.PADDLEOCR.value,
                ParserProfile.SCANNED,
                "high scanned-page ratio / low text density",
            )
        if (
            inspection.probable_formula_density >= 0.25
            or inspection.probable_table_density >= 0.35
            or (inspection.column_count_estimate or 1) >= 2
        ):
            return (
                ParserName.MINERU.value,
                ParserProfile.SCIENTIFIC,
                "scientific/complex PDF layout signals",
            )
        return ParserName.DOCLING.value, ParserProfile.BALANCED, "general text-native PDF"

    return ParserName.DOCLING.value, ParserProfile.BALANCED, "default enterprise parser"


@dataclass
class AutomaticParserRouter:
    """Select primary/fallback parsers from inspection and profiles."""

    profiles: dict[ParserProfile, ParserRouteProfile] = field(
        default_factory=lambda: dict(DEFAULT_ROUTE_PROFILES)
    )
    registered_names: frozenset[str] | None = None

    def select(
        self,
        *,
        inspection: ParserInspection,
        options: ParseOptions | None = None,
        filename: str = "",
    ) -> ParserSelection:
        opts = options or ParseOptions()
        override = opts.parser_override
        if override is not None and parser_key(override) not in {"", "auto"}:
            profile = opts.profile
            primary = parser_key(override)
            fallbacks = [parser_key(item) for item in opts.fallback_parsers] or [
                parser_key(item)
                for item in self.profiles.get(profile, ParserRouteProfile(override)).fallbacks
            ]
            return ParserSelection(
                primary=primary,
                fallbacks=[item for item in fallbacks if item != primary],
                profile=profile,
                reason=f"explicit parser override: {primary}",
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
            primary = parser_key(route.primary)
            # When inspection strongly disagrees with a balanced profile, prefer recommendation.
            if profile is ParserProfile.BALANCED and recommended_parser != primary:
                primary = recommended_parser
            fallbacks = [
                parser_key(item) for item in route.fallbacks if parser_key(item) != primary
            ]

        fallbacks = self._filter_registered(fallbacks, skip={primary})
        if (
            self.registered_names is not None
            and primary not in self.registered_names
            and fallbacks
        ):
            primary = fallbacks[0]
            fallbacks = fallbacks[1:]
        return ParserSelection(
            primary=primary,
            fallbacks=fallbacks,
            profile=profile,
            reason=reason,
            inspection=inspection,
        )

    def _filter_registered(self, names: list[str], *, skip: set[str]) -> list[str]:
        filtered: list[str] = []
        for name in names:
            if name in skip:
                continue
            if self.registered_names is not None and name not in self.registered_names:
                continue
            filtered.append(name)
        return filtered
