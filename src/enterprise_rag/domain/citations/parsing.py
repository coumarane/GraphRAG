"""Parse structured answer payloads from the answer model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class GroundedAnswerPayload(BaseModel):
    """Expected structured generation payload."""

    model_config = ConfigDict(extra="ignore")

    answer: str = Field(min_length=1)
    citation_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass
class ParsedGeneration:
    """Normalized parse result from free-form or JSON model output."""

    answer: str
    citation_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    structured: bool = False


def parse_generation_text(text: str) -> ParsedGeneration:
    """Parse model text as structured JSON when possible, else plain answer."""
    stripped = text.strip()
    if not stripped:
        return ParsedGeneration(answer="", warnings=["empty_generation"])

    candidate = _extract_json_candidate(stripped)
    if candidate is not None:
        try:
            normalized = dict(candidate)
            warnings_raw = normalized.get("warnings")
            if isinstance(warnings_raw, str):
                normalized["warnings"] = [warnings_raw] if warnings_raw.strip() else []
            elif warnings_raw is None:
                normalized["warnings"] = []
            elif isinstance(warnings_raw, list):
                normalized["warnings"] = [
                    str(item) for item in warnings_raw if str(item).strip()
                ]
            citation_raw = normalized.get("citation_ids")
            if isinstance(citation_raw, str):
                normalized["citation_ids"] = [citation_raw] if citation_raw.strip() else []
            payload = GroundedAnswerPayload.model_validate(normalized)
            return ParsedGeneration(
                answer=payload.answer.strip(),
                citation_ids=list(dict.fromkeys(payload.citation_ids)),
                warnings=list(payload.warnings),
                structured=True,
            )
        except (ValidationError, TypeError, ValueError):
            pass

    return ParsedGeneration(answer=stripped, structured=False)


def _extract_json_candidate(text: str) -> dict[str, object] | None:
    fenced = _JSON_FENCE_RE.search(text)
    raw = fenced.group(1) if fenced else None
    if raw is None:
        match = _JSON_OBJECT_RE.search(text)
        raw = match.group(0) if match else None
    if raw is None:
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None
