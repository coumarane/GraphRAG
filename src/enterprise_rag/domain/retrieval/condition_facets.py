"""Structured measurement-condition / axis facets for retrieval alignment.

Scales across documents by matching typed query features to chunk facets,
not by hardcoding product-slide phrases (tint/pH title strings, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.domain.modality import Modality

# Canonical measurement parameters (document-agnostic).
_PARAMETER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ph", re.compile(r"\bpH\b", re.IGNORECASE)),
    ("temperature", re.compile(r"\btemp(?:erature)?\b|\b°\s*C\b|\bdeg(?:rees?)?\s*C\b", re.IGNORECASE)),
    ("concentration", re.compile(r"\bconc(?:entration)?\b|\bwt\s*%|\b%?\s*w/?w\b", re.IGNORECASE)),
    ("humidity", re.compile(r"\bhumidity\b|\bRH\b")),
    ("wavelength", re.compile(r"\bwavelength\b|\bnm\b", re.IGNORECASE)),
)

# Appearance / physical-effect phenomena (not assay).
_PHENOMENON_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("tinting", re.compile(r"\btint(?:ing|ed)?\b", re.IGNORECASE)),
    ("color", re.compile(r"\bcolou?r(?:ation|ing)?\b", re.IGNORECASE)),
    ("appearance", re.compile(r"\bappearance\b", re.IGNORECASE)),
    ("texture", re.compile(r"\btexture\b|\bsmoothness\b|\bfriction\b", re.IGNORECASE)),
    ("stability", re.compile(r"\bstability\b|\bstable\b", re.IGNORECASE)),
)

# Topics that often collide with condition-axis questions (MIC tables vs tint axis).
_TOPIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mic", re.compile(r"\bMIC\b|\bminimum\s+inhibitory\b", re.IGNORECASE)),
    ("assay", re.compile(r"\bheavy\s+metal|\bassay\b|\bppm\b|\bmg/kg\b", re.IGNORECASE)),
    ("growth", re.compile(r"\bno\s+growth\b|\binhibitory\b", re.IGNORECASE)),
)

_RANGE_CUE = re.compile(
    r"\brange\b|\bover which\b|\bfrom\b.+\bto\b|\bvalues?\b.{0,24}\b"
    r"(?:test|tested|perform(?:ed)?|measur(?:ed|ement)?|evaluat)",
    re.IGNORECASE | re.DOTALL,
)
_NUMERIC = re.compile(r"\d+(?:\.\d+)?")
_GLUED_NUM_ALPHA = re.compile(r"(?<=\d)(?=[A-Za-z\u3040-\u30ff\u4e00-\u9fff])")


class AxisRange(BaseModel):
    """Numeric axis/condition span for one parameter."""

    model_config = ConfigDict(extra="forbid")

    parameter: str
    min: float
    max: float
    ticks: list[float] = Field(default_factory=list)


class ConditionFacets(BaseModel):
    """Typed condition metadata stored on chunks / elements."""

    model_config = ConfigDict(extra="forbid")

    parameters: list[str] = Field(default_factory=list)
    ranges: list[AxisRange] = Field(default_factory=list)
    phenomena: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.parameters or self.ranges or self.phenomena or self.topics)

    def to_metadata(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> ConditionFacets | None:
        if not isinstance(raw, Mapping) or not raw:
            return None
        try:
            return cls.model_validate(raw)
        except Exception:  # noqa: BLE001 - best-effort payload parse
            return None


@dataclass(frozen=True)
class QueryFeatures:
    """Typed retrieval features derived from question shape (not slide titles)."""

    asks_condition_range: bool = False
    condition_parameters: tuple[str, ...] = ()
    phenomena: tuple[str, ...] = ()
    conflict_topics: tuple[str, ...] = ()
    prefer_modality: Modality | None = None

    @property
    def prefer_chart(self) -> bool:
        return self.prefer_modality is Modality.CHART


def detect_parameters(text: str) -> list[str]:
    found: list[str] = []
    for name, pattern in _PARAMETER_PATTERNS:
        if pattern.search(text) and name not in found:
            found.append(name)
    return found


def detect_phenomena(text: str) -> list[str]:
    found: list[str] = []
    for name, pattern in _PHENOMENON_PATTERNS:
        if pattern.search(text) and name not in found:
            found.append(name)
    return found


def detect_topics(text: str) -> list[str]:
    found: list[str] = []
    for name, pattern in _TOPIC_PATTERNS:
        if pattern.search(text) and name not in found:
            found.append(name)
    return found


def extract_axis_ranges(text: str) -> list[AxisRange]:
    """Find parameter labels followed by a dense numeric tick run (≥4 values)."""
    if not text:
        return []
    ranges: list[AxisRange] = []
    seen: set[tuple[str, float, float]] = set()
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        spaced = _GLUED_NUM_ALPHA.sub(" ", line)
        for param, pattern in _PARAMETER_PATTERNS:
            if not pattern.search(spaced):
                continue
            values = [float(match) for match in _NUMERIC.findall(spaced)]
            if len(values) < 4:
                continue
            low, high = values[0], values[-1]
            if high < low:
                low, high = high, low
            key = (param, low, high)
            if key in seen:
                continue
            seen.add(key)
            ranges.append(AxisRange(parameter=param, min=low, max=high, ticks=values))
    return ranges


def extract_condition_facets(text: str) -> ConditionFacets:
    """Derive facets from free text (ingest enrichment or query-time fallback)."""
    ranges = extract_axis_ranges(text)
    parameters = detect_parameters(text)
    for axis in ranges:
        if axis.parameter not in parameters:
            parameters.append(axis.parameter)
    return ConditionFacets(
        parameters=parameters,
        ranges=ranges,
        phenomena=detect_phenomena(text),
        topics=detect_topics(text),
    )


def facets_from_chart_axes(axes: Mapping[str, Any] | None) -> ConditionFacets:
    """Map vision/chart axis dicts into the shared facet schema."""
    if not axes:
        return ConditionFacets()
    blob = " ".join(f"{key} {value}" for key, value in axes.items() if value is not None)
    return extract_condition_facets(blob)


def merge_facets(*parts: ConditionFacets | None) -> ConditionFacets:
    parameters: list[str] = []
    ranges: list[AxisRange] = []
    phenomena: list[str] = []
    topics: list[str] = []
    range_keys: set[tuple[str, float, float]] = set()
    for part in parts:
        if part is None or part.is_empty:
            continue
        for name in part.parameters:
            if name not in parameters:
                parameters.append(name)
        for axis in part.ranges:
            key = (axis.parameter, axis.min, axis.max)
            if key in range_keys:
                continue
            range_keys.add(key)
            ranges.append(axis)
        for name in part.phenomena:
            if name not in phenomena:
                phenomena.append(name)
        for name in part.topics:
            if name not in topics:
                topics.append(name)
    return ConditionFacets(
        parameters=parameters,
        ranges=ranges,
        phenomena=phenomena,
        topics=topics,
    )


def facets_from_elements(elements: Sequence[Any]) -> ConditionFacets:
    """Collect facets from element metadata and chart axes."""
    parts: list[ConditionFacets] = []
    for element in elements:
        metadata = getattr(element, "metadata", None)
        if isinstance(metadata, Mapping):
            stored = ConditionFacets.from_mapping(metadata.get("condition_facets"))  # type: ignore[arg-type]
            if stored is not None:
                parts.append(stored)
        axes = getattr(element, "axes", None)
        if isinstance(axes, Mapping) and axes:
            parts.append(facets_from_chart_axes(axes))
        conditions = None
        if isinstance(metadata, Mapping):
            conditions = metadata.get("measurement_conditions")
        if isinstance(conditions, str) and conditions.strip():
            parts.append(extract_condition_facets(conditions))
    return merge_facets(*parts)


def prose_for_facets(facets: ConditionFacets) -> str:
    """Optional embedding-friendly lines derived from facets (not slide titles)."""
    lines: list[str] = []
    for axis in facets.ranges:
        tick_text = ", ".join(str(v) for v in axis.ticks) if axis.ticks else ""
        line = f"{axis.parameter} axis range: {axis.min} to {axis.max}"
        if tick_text:
            line += f" (ticks: {tick_text})"
        lines.append(line)
    return "\n".join(lines)


def detect_query_features(question: str) -> QueryFeatures:
    """Shape-based query features: parameter + range cue, not product phrases."""
    parameters = tuple(detect_parameters(question))
    phenomena = tuple(detect_phenomena(question))
    has_range_cue = bool(_RANGE_CUE.search(question))
    asks = bool(parameters) and (has_range_cue or bool(phenomena))
    # Appearance phenomena + condition parameter → prefer chart axis over assay/MIC tables.
    appearance = tuple(name for name in phenomena if name in {"tinting", "color", "appearance"})
    conflict: tuple[str, ...] = ()
    prefer_modality: Modality | None = None
    if asks and appearance:
        conflict = ("mic", "assay", "growth")
        prefer_modality = Modality.CHART
    elif asks and has_range_cue:
        prefer_modality = Modality.CHART
    return QueryFeatures(
        asks_condition_range=asks,
        condition_parameters=parameters,
        phenomena=phenomena,
        conflict_topics=conflict,
        prefer_modality=prefer_modality,
    )


@dataclass
class FacetAlignmentScore:
    """Debug-friendly alignment breakdown."""

    boost: float = 0.0
    reasons: list[str] = field(default_factory=list)


def score_facet_alignment(
    *,
    features: QueryFeatures,
    facets: ConditionFacets,
) -> FacetAlignmentScore:
    """Score how well chunk facets answer a condition-range question."""
    if not features.asks_condition_range:
        return FacetAlignmentScore()
    result = FacetAlignmentScore()
    param_overlap = set(features.condition_parameters) & set(facets.parameters)
    if param_overlap:
        result.boost += 0.9
        result.reasons.append("parameter_overlap")
    range_hit = any(axis.parameter in features.condition_parameters for axis in facets.ranges)
    if range_hit:
        result.boost += 1.2
        result.reasons.append("axis_range")
    phenomenon_overlap = set(features.phenomena) & set(facets.phenomena)
    if phenomenon_overlap:
        result.boost += 1.0
        result.reasons.append("phenomenon_overlap")
    if features.conflict_topics:
        conflict = set(features.conflict_topics) & set(facets.topics)
        # Demote assay/MIC bleed only when the chunk is not also about the asked phenomenon.
        if conflict and not phenomenon_overlap:
            result.boost -= 1.2
            result.reasons.append("conflict_topic")
    return result
