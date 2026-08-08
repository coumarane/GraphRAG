"""Query normalization, modality hints and retrieval-mode selection."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.retrieval.enums import RetrievalMode

_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_/]{1,}", re.IGNORECASE)
_CURRENT_QUESTION_RE = re.compile(
    r"(?is)(?:^|\n)\s*Current question:\s*(.+?)(?:\n\s*\n|\n\s*Answer the current question|\Z)"
)
# Slide titles often live in TEXT chunks; expand keyword queries for lexical/dense recall.
_RETRIEVAL_EXPANSIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bsolar\s+radiation\b", re.IGNORECASE),
        "near-infrared near infrared NIR NATUTECT UV Near-IR reflective pigments",
    ),
    (
        re.compile(r"\btexture\s+evaluation\b", re.IGNORECASE),
        "SILKYFLAKE Surface-Treated Products FTD008FY-F130 FTD008FY-F190 "
        "FTD008FY-F840 MIU MMD smoothness slip Aluminum Stearate",
    ),
    (
        re.compile(r"\bmiu\b", re.IGNORECASE),
        "MMD Texture evaluation friction coefficient of dynamic friction SILKYFLAKE",
    ),
    (
        re.compile(r"\bmmd\b", re.IGNORECASE),
        "MIU Texture evaluation smoothness SILKYFLAKE Surface-Treated",
    ),
    (
        re.compile(r"\bnear[-\s]?infrared\b|\bnir\b", re.IGNORECASE),
        "solar radiation NATUTECT Near-IR reflective",
    ),
)

_MULTIMODAL_HINTS = frozenset(
    {
        "chart",
        "charts",
        "figure",
        "figures",
        "image",
        "images",
        "diagram",
        "diagrams",
        "table",
        "tables",
        "equation",
        "equations",
        "plot",
        "graph",
        "visual",
        "photo",
    }
)
_ASSAY_HINTS = frozenset(
    {
        "assay",
        "impurity",
        "impurities",
        "heavy metal",
        "heavy metals",
        "ppm",
        "specification",
        "specifications",
        "particle size",
        "surface area",
        "d50",
        "μm",
        "um",
        "mg/kg",
        "content",
        "composition",
        "inci",
        "cas",
        "pb",
        "cd",
        "as",
        "hg",
        "ni",
        "cr",
        "lead",
        "cadmium",
        "arsenic",
        "mercury",
        "nickel",
        "chromium",
    }
)
_GLOBAL_HINTS = frozenset(
    {
        "overview",
        "summarize",
        "summary",
        "across",
        "compare",
        "comparison",
        "theme",
        "themes",
        "community",
        "overall",
        "all documents",
        "suppliers",
    }
)
_LOCAL_HINTS = frozenset(
    {
        "related",
        "relationship",
        "connected",
        "how is",
        "linked",
        "neighbor",
        "entity",
        "regulation",
        "ingredient",
    }
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "what",
        "which",
        "who",
        "how",
        "does",
        "do",
        "is",
        "are",
        "about",
        "show",
        "tell",
        "me",
        "please",
    }
)


@dataclass(frozen=True)
class QueryAnalysis:
    """Deterministic analysis used to select retrieval branches."""

    normalized_question: str
    language: str
    tokens: list[str]
    entity_mentions: list[str]
    modality_hints: list[Modality]
    selected_modes: list[RetrievalMode]
    intent_labels: list[str] = field(default_factory=list)


def normalize_question(question: str) -> str:
    """NFKC-normalize, collapse whitespace and strip."""
    folded = unicodedata.normalize("NFKC", question).strip()
    return _SPACE_RE.sub(" ", folded)


def extract_focus_question(question: str) -> str:
    """Prefer the ``Current question:`` line when chat history was prepended.

    Conversational wrappers pollute intent detection and embeddings with prior
    product names (e.g. METASHINE RC) even when the user asked about another slide.
    """
    match = _CURRENT_QUESTION_RE.search(question)
    if match:
        focus = match.group(1).strip()
        if focus:
            return focus
    return question.strip()


def expand_for_retrieval(question: str) -> str:
    """Append synonym phrases for known slide/topic keywords."""
    extras: list[str] = []
    for pattern, expansion in _RETRIEVAL_EXPANSIONS:
        if pattern.search(question):
            extras.append(expansion)
    if not extras:
        return question
    return normalize_question(f"{question} {' '.join(extras)}")


def detect_language(question: str) -> str:
    """Lightweight language guess (latin vs non-latin heuristic)."""
    letters = [ch for ch in question if ch.isalpha()]
    if not letters:
        return "und"
    non_ascii = sum(1 for ch in letters if ord(ch) > 127)
    if non_ascii / max(1, len(letters)) > 0.3:
        return "mul"
    return "en"


def tokenize(question: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(question)]


def extract_entity_mentions(question: str) -> list[str]:
    """Heuristic entity mentions: capitalized spans and multi-token content words."""
    mentions: list[str] = []
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*)\b", question):
        mentions.append(match.group(1))
    tokens = [token for token in tokenize(question) if token not in _STOPWORDS and len(token) > 2]
    # Prefer longer content tokens as soft entity candidates.
    for token in tokens:
        if token not in {m.casefold() for m in mentions}:
            mentions.append(token)
    return mentions[:12]


def detect_modality_hints(question: str) -> list[Modality]:
    lowered = question.casefold()
    hints: list[Modality] = []
    mapping = {
        Modality.CHART: (
            "chart",
            "plot",
            "graph",
            "l*",
            "angle of measurement",
            "soft-focus",
            "soft focus",
            "tone-up",
            "tone up",
            "byk",
            "synthetic mica",
            "gloss type",
            "matte type",
            "measurement conditions",
            "texture evaluation",
            "miu",
            "mmd",
            "smoothness",
            "slip",
        ),
        Modality.IMAGE: ("image", "photo", "figure", "visual", "sem", "micrograph"),
        Modality.DIAGRAM: (
            "diagram",
            "solar radiation",
            "near-infrared",
            "near infrared",
            "nir protection",
            "natutect",
        ),
        Modality.TABLE: (
            "table",
            "assay",
            "impurity",
            "impurities",
            "heavy metal",
            "heavy metals",
            "ppm",
            "specification",
            "particle size",
            "surface area",
            "composition",
            "content",
        ),
        Modality.EQUATION: ("equation", "formula"),
    }
    for modality, words in mapping.items():
        if any(word in lowered for word in words):
            hints.append(modality)
    # Appearance / angle chart questions should not be dominated by assay tables.
    chartish = any(
        token in lowered
        for token in (
            "appearance",
            "angle of measurement",
            "soft-focus",
            "soft focus",
            "tone-up",
            "tone up",
            "byk",
            "synthetic mica",
            "comparison with synthetic",
        )
    )
    if chartish and "heavy metal" not in lowered and "ppm" not in lowered:
        hints = [item for item in hints if item is not Modality.TABLE]
        if Modality.CHART not in hints:
            hints.insert(0, Modality.CHART)
    # "Does the appearance chart report heavy metals?" is a chart-scope question,
    # not an assay lookup — keep chart modality ahead of tables.
    if (
        "heavy metal" in lowered
        and any(token in lowered for token in ("appearance", "tone-up", "l*", "angle"))
        and any(token in lowered for token in ("chart", "slide", "page", "report", "show"))
    ):
        hints = [Modality.CHART, *[item for item in hints if item is not Modality.TABLE]]
    return hints


def classify_intent(question: str) -> list[str]:
    lowered = question.casefold()
    labels: list[str] = []
    if any(hint in lowered for hint in _ASSAY_HINTS):
        labels.append("assay")
        labels.append("multimodal")
    if any(hint in lowered for hint in _MULTIMODAL_HINTS):
        labels.append("multimodal")
    if any(hint in lowered for hint in _GLOBAL_HINTS):
        labels.append("global")
    if any(hint in lowered for hint in _LOCAL_HINTS):
        labels.append("local")
    tokens = tokenize(question)
    # Short keyword queries ("Texture evaluation chart") are factual lookups.
    if (
        "?" in question
        or lowered.startswith(("what", "when", "where", "why", "how", "give", "find", "show"))
        or len(tokens) <= 8
    ):
        labels.append("factual")
    if not labels:
        labels.append("general")
    # Preserve order while deduping.
    seen: set[str] = set()
    ordered: list[str] = []
    for label in labels:
        if label in seen:
            continue
        seen.add(label)
        ordered.append(label)
    return ordered


def select_modes(
    *,
    requested: RetrievalMode,
    intent_labels: list[str],
    modality_hints: list[Modality],
) -> list[RetrievalMode]:
    """Map requested mode / auto classification to concrete executable modes."""
    if requested is RetrievalMode.AUTO:
        modes: list[RetrievalMode] = []
        if "assay" in intent_labels:
            # Assay/spec questions need lexical + dense + table-aware multimodal.
            modes.extend(
                [
                    RetrievalMode.HYBRID,
                    RetrievalMode.MULTIMODAL,
                    RetrievalMode.NAIVE,
                ]
            )
        if "multimodal" in intent_labels or modality_hints:
            modes.append(RetrievalMode.MULTIMODAL)
            # Chart titles / captions are often TEXT chunks — never multimodal-only.
            modes.append(RetrievalMode.HYBRID)
        if "global" in intent_labels:
            modes.append(RetrievalMode.GLOBAL)
        if "local" in intent_labels:
            modes.append(RetrievalMode.LOCAL)
        if not modes:
            modes.append(RetrievalMode.HYBRID)
        # Always include a dense branch for factual/general questions.
        if RetrievalMode.NAIVE not in modes and "factual" in intent_labels:
            modes.insert(0, RetrievalMode.NAIVE)
        if RetrievalMode.HYBRID not in modes and "factual" in intent_labels:
            modes.append(RetrievalMode.HYBRID)
        return _unique(modes)

    if requested is RetrievalMode.MIX:
        return [
            RetrievalMode.LOCAL,
            RetrievalMode.GLOBAL,
            RetrievalMode.NAIVE,
            RetrievalMode.MULTIMODAL,
            RetrievalMode.HYBRID,
        ]
    if requested is RetrievalMode.HYBRID:
        return [RetrievalMode.HYBRID]
    return [requested]


def analyze_query(question: str, *, mode: RetrievalMode) -> QueryAnalysis:
    focus = normalize_question(extract_focus_question(question))
    retrieval_question = expand_for_retrieval(focus)
    intent_labels = classify_intent(focus)
    modality_hints = detect_modality_hints(focus)
    return QueryAnalysis(
        normalized_question=retrieval_question,
        language=detect_language(focus),
        tokens=tokenize(focus),
        entity_mentions=extract_entity_mentions(focus),
        modality_hints=modality_hints,
        selected_modes=select_modes(
            requested=mode,
            intent_labels=intent_labels,
            modality_hints=modality_hints,
        ),
        intent_labels=intent_labels,
    )


def _unique(modes: list[RetrievalMode]) -> list[RetrievalMode]:
    seen: set[RetrievalMode] = set()
    ordered: list[RetrievalMode] = []
    for mode in modes:
        if mode in seen:
            continue
        seen.add(mode)
        ordered.append(mode)
    return ordered
