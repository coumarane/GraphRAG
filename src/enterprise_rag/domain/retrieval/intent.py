"""Query normalization, modality hints and retrieval-mode selection."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.retrieval.enums import RetrievalMode

_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_/]{1,}", re.IGNORECASE)

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
        Modality.CHART: ("chart", "plot", "graph"),
        Modality.IMAGE: ("image", "photo", "figure", "visual"),
        Modality.DIAGRAM: ("diagram",),
        Modality.TABLE: ("table",),
        Modality.EQUATION: ("equation", "formula"),
    }
    for modality, words in mapping.items():
        if any(word in lowered for word in words):
            hints.append(modality)
    return hints


def classify_intent(question: str) -> list[str]:
    lowered = question.casefold()
    labels: list[str] = []
    if any(hint in lowered for hint in _MULTIMODAL_HINTS):
        labels.append("multimodal")
    if any(hint in lowered for hint in _GLOBAL_HINTS):
        labels.append("global")
    if any(hint in lowered for hint in _LOCAL_HINTS):
        labels.append("local")
    if "?" in question or lowered.startswith(("what", "when", "where", "why", "how")):
        labels.append("factual")
    if not labels:
        labels.append("general")
    return labels


def select_modes(
    *,
    requested: RetrievalMode,
    intent_labels: list[str],
    modality_hints: list[Modality],
) -> list[RetrievalMode]:
    """Map requested mode / auto classification to concrete executable modes."""
    if requested is RetrievalMode.AUTO:
        modes: list[RetrievalMode] = []
        if "multimodal" in intent_labels or modality_hints:
            modes.append(RetrievalMode.MULTIMODAL)
        if "global" in intent_labels:
            modes.append(RetrievalMode.GLOBAL)
        if "local" in intent_labels:
            modes.append(RetrievalMode.LOCAL)
        if not modes:
            modes.append(RetrievalMode.HYBRID)
        # Always include a dense branch for factual/general questions.
        if RetrievalMode.NAIVE not in modes and "factual" in intent_labels:
            modes.insert(0, RetrievalMode.NAIVE)
        return _unique(modes)

    if requested is RetrievalMode.MIX:
        return [
            RetrievalMode.LOCAL,
            RetrievalMode.GLOBAL,
            RetrievalMode.NAIVE,
            RetrievalMode.MULTIMODAL,
        ]
    if requested is RetrievalMode.HYBRID:
        return [RetrievalMode.HYBRID]
    return [requested]


def analyze_query(question: str, *, mode: RetrievalMode) -> QueryAnalysis:
    normalized = normalize_question(question)
    intent_labels = classify_intent(normalized)
    modality_hints = detect_modality_hints(normalized)
    return QueryAnalysis(
        normalized_question=normalized,
        language=detect_language(normalized),
        tokens=tokenize(normalized),
        entity_mentions=extract_entity_mentions(normalized),
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
