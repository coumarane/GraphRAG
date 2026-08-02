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
    combined: list[str] = []
    seen: set[str] = set()
    for citation_id in [*from_text, *claimed]:
        if citation_id in seen:
            continue
        seen.add(citation_id)
        combined.append(citation_id)

    unknown = [cid for cid in combined if not registry.contains(cid)]
    warnings: list[str] = []
    if unknown:
        if strict:
            raise CitationValidationError(
                "Answer cited unknown citation IDs",
                details={"unknown_ids": unknown, "allowed": registry.ids()},
            )
        warnings.append(f"stripped_unknown_citations:{','.join(unknown)}")

    allowed = set(registry.ids())
    cleaned_answer = strip_unknown_citation_refs(answer, allowed_ids=allowed)
    known_ids = [cid for cid in combined if cid in allowed]
    citations = registry.select(known_ids)

    # Identity / page / element checks against registry records.
    for citation in citations:
        _assert_citation_integrity(tenant, citation, registry)

    if not citations and registry.ids():
        warnings.append("answer_missing_citations")

    return CitationValidationResult(
        answer=cleaned_answer,
        citations=citations,
        cited_ids=known_ids,
        unknown_ids=unknown,
        warnings=warnings,
        valid=not unknown,
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
