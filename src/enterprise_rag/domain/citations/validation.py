"""Post-generation citation and grounding validation."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from enterprise_rag.domain.citations.models import Citation
from enterprise_rag.domain.citations.registry import CitationRegistry
from enterprise_rag.domain.retrieval.models import GraphPath
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import CitationValidationError

_CITATION_REF_RE = re.compile(r"\[(C\d+)\]")
# Full abstention / "not found" language — not claim-fidelity hedges alone.
_INSUFFICIENT_ANSWER_RE = re.compile(
    r"(?is)\b("
    r"no .+ (?:in|from) the (?:provided )?evidence"
    r"|not (?:found|present|available|included) in the (?:provided )?evidence"
    r"|no explicit .+ (?:found|available|provided|in the)"
    r"|does not (?:provide|contain|include|mention|state).{0,60}"
    r"(?:information|details|data|evidence).{0,40}"
    r"(?:regarding|about|on|for|in the)"
    r"|cannot be confirmed (?:from|in) the (?:provided )?evidence"
    r"|could not find (?:enough |any )?(?:retrieved )?evidence"
    r"|evidence (?:is|was) insufficient"
    r"|insufficient (?:evidence|information)(?:\s+in\s+the|\s+to\s+)"
    r"|unable to (?:confirm|determine|find|answer).{0,40}(?:evidence|sources)"
    r")\b"
)
# Positive grounded claims — if present, keep citations even with a fidelity hedge.
_POSITIVE_GROUNDED_CLAIM_RE = re.compile(
    r"(?i)("
    r"\d+(?:\.\d+)?\s*%"
    r"|\bcontains\b.{0,40}\d"
    r"|\buses\b.{0,40}\d"
    r"|\b(?:is|was|were)\b.{0,20}\d+(?:\.\d+)?\s*%"
    r"|\bexample\b.{0,60}\d+(?:\.\d+)?\s*%"
    r")"
)
# "No recommended/official level" is claim-strength fidelity, not a full abstention.
_CLAIM_FIDELITY_HEDGE_RE = re.compile(
    r"(?i)does not (?:specify|provide|state|include).{0,100}"
    r"(?:recommended|official|specified|approved|labelled|labeled|explicit recommended)"
)


def is_insufficient_evidence_answer(answer: str) -> bool:
    """True when the answer is a full abstention (no supported ask), not a partial reply.

    Claim-fidelity hedges like \"evidence does not specify a recommended use level\"
    must NOT clear citations when the answer still states tested/example values.
    """
    text = answer or ""
    if not text.strip():
        return False
    if _CLAIM_FIDELITY_HEDGE_RE.search(text) and _POSITIVE_GROUNDED_CLAIM_RE.search(text):
        return False
    if _POSITIVE_GROUNDED_CLAIM_RE.search(text) and not re.search(
        r"(?i)no .+ (?:in|from) the (?:provided )?evidence"
        r"|cannot be confirmed (?:from|in) the (?:provided )?evidence"
        r"|not (?:found|present|available|included) in the (?:provided )?evidence",
        text,
    ):
        # Concrete numeric/example claims without a global "not in evidence" closer.
        return False
    return bool(_INSUFFICIENT_ANSWER_RE.search(text))


_METAL_CLAIM_RE = re.compile(
    r"(?i)\b(lead|pb|cadmium|cd|arsenic|as|mercury|hg|chromium|cr|antimony|sb|"
    r"barium|ba|nickel|ni|zinc|zn|tin|sn)\b"
    r"(?:\s*\([^)]*\))?\s*[:\-]\s*([^\n\[]{1,80})"
)
_LESS_THAN_RE = re.compile(r"(?i)less\s+than\s+(\d+(?:\.\d+)?)")
_PPM_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*ppm")


@dataclass(frozen=True)
class CitationValidationResult:
    """Outcome of validating model-emitted citations against the registry."""

    answer: str
    citations: list[Citation]
    cited_ids: list[str]
    unknown_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    valid: bool = True


def extract_citation_ids(answer: str) -> list[str]:
    """Extract ordered unique ``[Cn]`` references from answer text."""
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _CITATION_REF_RE.finditer(answer):
        citation_id = match.group(1)
        if citation_id in seen:
            continue
        seen.add(citation_id)
        ordered.append(citation_id)
    return ordered


def strip_unknown_citation_refs(answer: str, *, allowed_ids: set[str]) -> str:
    """Remove ``[Cn]`` markers that are not in the allowlist."""

    def _replace(match: re.Match[str]) -> str:
        citation_id = match.group(1)
        return match.group(0) if citation_id in allowed_ids else ""

    cleaned = _CITATION_REF_RE.sub(_replace, answer)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def validate_numeric_grounding(
    *,
    answer: str,
    citations: Sequence[Citation],
) -> list[str]:
    """Flag quantitative metal claims unsupported by cited evidence text."""
    if not answer.strip() or not citations:
        return []
    corpus = "\n".join((citation.evidence or "").casefold() for citation in citations)
    if not corpus.strip():
        return []
    warnings: list[str] = []
    for match in _METAL_CLAIM_RE.finditer(answer):
        metal = match.group(1).casefold()
        value = match.group(2).strip()
        if not value or value.lower() in {"see evidence", "not listed", "not provided"}:
            continue
        if not _claim_supported_in_corpus(metal=metal, value=value, corpus=corpus):
            warnings.append(f"ungrounded_numeric:{metal}:{value[:48]}")
    return warnings


def _claim_supported_in_corpus(*, metal: str, value: str, corpus: str) -> bool:
    value_cf = value.casefold()
    metal_aliases = {
        "lead": ("lead", "pb"),
        "pb": ("lead", "pb"),
        "cadmium": ("cadmium", "cd"),
        "cd": ("cadmium", "cd"),
        "arsenic": ("arsenic", "as"),
        "as": ("arsenic", "as"),
        "mercury": ("mercury", "hg"),
        "hg": ("mercury", "hg"),
        "chromium": ("chromium", "cr"),
        "cr": ("chromium", "cr"),
        "antimony": ("antimony", "sb"),
        "sb": ("antimony", "sb"),
        "barium": ("barium", "ba"),
        "ba": ("barium", "ba"),
        "nickel": ("nickel", "ni"),
        "ni": ("nickel", "ni"),
        "zinc": ("zinc", "zn"),
        "zn": ("zinc", "zn"),
        "tin": ("tin", "sn"),
        "sn": ("tin", "sn"),
    }.get(metal, (metal,))

    if "not detected" in value_cf or "n.d" in value_cf:
        return _metal_near_token(corpus, metal_aliases, ("n.d", "not detected"))

    less = _LESS_THAN_RE.search(value_cf)
    if less:
        number = less.group(1)
        phrases = (f"less than {number}", f"<{number}", f"< {number}")
        return any(phrase in corpus for phrase in phrases) and any(
            alias in corpus for alias in metal_aliases
        )

    ppm = _PPM_RE.search(value_cf)
    if ppm:
        number = ppm.group(1)
        return (f"{number} ppm" in corpus or f"{number}ppm" in corpus) and any(
            alias in corpus for alias in metal_aliases
        )

    snippet = re.sub(r"\s+", " ", value_cf)[:40]
    return bool(
        snippet and snippet in corpus and any(alias in corpus for alias in metal_aliases)
    )


def _metal_near_token(
    corpus: str,
    metal_aliases: tuple[str, ...],
    value_tokens: tuple[str, ...],
) -> bool:
    for alias in metal_aliases:
        for token in value_tokens:
            if re.search(
                rf"{re.escape(alias)}.{{0,40}}{re.escape(token)}|"
                rf"{re.escape(token)}.{{0,40}}{re.escape(alias)}",
                corpus,
            ):
                return True
    return False


def validate_citations(
    *,
    tenant: TenantContext,
    answer: str,
    registry: CitationRegistry,
    claimed_ids: Sequence[str] | None = None,
    strict: bool = False,
) -> CitationValidationResult:
    """Validate cited IDs against registry and tenant/document identity.

    When ``strict`` is True, unknown IDs raise ``CitationValidationError``.
    Otherwise unknown refs are stripped and recorded as warnings.
    """
    if registry.tenant.tenant_id != tenant.tenant_id:
        raise CitationValidationError(
            "Citation registry tenant mismatch",
            details={
                "expected": str(tenant.tenant_id),
                "actual": str(registry.tenant.tenant_id),
            },
        )

    from_text = extract_citation_ids(answer)
    claimed = list(claimed_ids or [])
    insufficient = is_insufficient_evidence_answer(answer)
    warnings: list[str] = []

    # Abstention / "not in evidence" answers must not surface source cards.
    # Models often still attach every retrieved [Cn]; strip them hard.
    if insufficient:
        candidate_ids: list[str] = []
        if from_text or claimed:
            warnings.append("citations_cleared_on_insufficient_answer")
    elif from_text:
        # Prefer markers actually written in the answer over unused JSON IDs.
        candidate_ids = from_text
    else:
        candidate_ids = claimed

    combined: list[str] = []
    seen: set[str] = set()
    for citation_id in candidate_ids:
        if citation_id in seen:
            continue
        seen.add(citation_id)
        combined.append(citation_id)

    unknown = [cid for cid in combined if not registry.contains(cid)]
    if unknown:
        if strict:
            raise CitationValidationError(
                "Answer cited unknown citation IDs",
                details={"unknown_ids": unknown, "allowed": registry.ids()},
            )
        warnings.append(f"stripped_unknown_citations:{','.join(unknown)}")

    allowed = set() if insufficient else set(registry.ids())
    cleaned_answer = strip_unknown_citation_refs(answer, allowed_ids=allowed)
    known_ids = [cid for cid in combined if cid in set(registry.ids())]
    citations = registry.select(known_ids)

    # Identity / page / element checks against registry records.
    for citation in citations:
        _assert_citation_integrity(tenant, citation, registry)

    if not citations and registry.ids() and not insufficient:
        warnings.append("answer_missing_citations")

    grounding_warnings = validate_numeric_grounding(
        answer=cleaned_answer,
        citations=citations,
    )
    if grounding_warnings and strict:
        raise CitationValidationError(
            "Answer contains quantitative claims not grounded in cited evidence",
            details={"ungrounded": grounding_warnings},
        )
    warnings.extend(grounding_warnings)

    return CitationValidationResult(
        answer=cleaned_answer,
        citations=citations,
        cited_ids=known_ids,
        unknown_ids=unknown,
        warnings=warnings,
        valid=not unknown and not grounding_warnings,
    )


def _assert_citation_integrity(
    tenant: TenantContext,
    citation: Citation,
    registry: CitationRegistry,
) -> None:
    registered = registry.get(citation.citation_id)
    if registered is None:
        raise CitationValidationError(
            "Citation missing from registry",
            details={"citation_id": citation.citation_id},
        )
    if citation.tenant_id != tenant.tenant_id:
        raise CitationValidationError(
            "Citation tenant mismatch",
            details={"citation_id": citation.citation_id},
        )
    if citation.document_id != registered.document_id:
        raise CitationValidationError(
            "Citation document identity mismatch",
            details={"citation_id": citation.citation_id},
        )
    if citation.document_version_id != registered.document_version_id:
        raise CitationValidationError(
            "Citation document version mismatch",
            details={"citation_id": citation.citation_id},
        )
    if citation.chunk_id != registered.chunk_id:
        raise CitationValidationError(
            "Citation chunk identity mismatch",
            details={"citation_id": citation.citation_id},
        )
    if citation.page_end < citation.page_start:
        raise CitationValidationError(
            "Citation page range invalid",
            details={"citation_id": citation.citation_id},
        )
    if (
        citation.element_id is not None
        and registered.element_id is not None
        and citation.element_id != registered.element_id
    ):
        raise CitationValidationError(
            "Citation element identity mismatch",
            details={"citation_id": citation.citation_id},
        )


def remap_graph_path_citations(
    paths: Sequence[GraphPath],
    registry: CitationRegistry,
) -> list[GraphPath]:
    """Map chunk-id or raw supporting refs onto registry citation IDs."""
    remapped: list[GraphPath] = []
    for path in paths:
        supporting: list[str] = []
        for ref in path.supporting_citations:
            if registry.contains(ref):
                supporting.append(ref)
                continue
            try:
                chunk_id = UUID(ref)
            except ValueError:
                continue
            citation_id = registry.citation_id_for_chunk(chunk_id)
            if citation_id is not None:
                supporting.append(citation_id)
        remapped.append(
            path.model_copy(update={"supporting_citations": list(dict.fromkeys(supporting))})
        )
    return remapped
