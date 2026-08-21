"""Enforce the six hard GraphRAG invariants at query time."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from enterprise_rag.domain.conversation.scope_expand import (
    AWAITING_SCOPE_EXPAND,
    DOCUMENT_SCOPE_EXPANDED,
    build_scope_miss_message,
)
from enterprise_rag.domain.generation.grounding_policy import (
    EvidenceSufficiency,
    assess_evidence,
    finalize_grounded_answer,
)
from enterprise_rag.domain.policies.hard_invariants import HardInvariant
from enterprise_rag.domain.retrieval.models import RetrievedEvidence
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import TenantError


@dataclass
class InvariantVerdict:
    """Result of applying hard invariants to a query turn."""

    enforced: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    block_answer: str | None = None
    answer: str | None = None

    def mark(self, invariant: HardInvariant) -> None:
        name = invariant.value
        if name not in self.enforced:
            self.enforced.append(name)

    def extend_warnings(self, items: Sequence[str]) -> None:
        for item in items:
            if item and item not in self.warnings:
                self.warnings.append(item)


class HardInvariantGate:
    """Central enforcement for the six hard system invariants."""

    def enforce_security(self, tenant: TenantContext, verdict: InvariantVerdict) -> None:
        """Invariant 6 — tenant must be authorized before any retrieval/generation."""
        try:
            tenant.ensure_authorized()
        except TenantError:
            verdict.blocked = True
            verdict.block_answer = (
                "Unauthorized tenant context. This request cannot be processed."
            )
            verdict.extend_warnings(["security_authorization_failed"])
            return
        verdict.mark(HardInvariant.SECURITY_AUTHORIZATION)

    def enforce_retrieval_scope(
        self,
        *,
        pinned_document_ids: Sequence[UUID],
        expanded: bool,
        verdict: InvariantVerdict,
    ) -> None:
        """Invariant 3 — scope stays pinned unless consent expands it."""
        if expanded:
            verdict.extend_warnings(
                [DOCUMENT_SCOPE_EXPANDED, "retrieval_scope_expanded_with_consent"]
            )
        elif pinned_document_ids:
            verdict.extend_warnings(["retrieval_scope_pinned"])
        verdict.mark(HardInvariant.RETRIEVAL_SCOPE)

    def enforce_conversation_context(
        self,
        *,
        has_active_context: bool,
        context_switch: bool,
        inferred: bool,
        verdict: InvariantVerdict,
    ) -> None:
        """Invariant 2 — sticky context from first Q/A (or explicit switch)."""
        if context_switch:
            verdict.extend_warnings(["conversation_context_switched", "context_switch_detected"])
        elif inferred:
            verdict.extend_warnings(["conversation_context_inferred"])
        elif has_active_context:
            verdict.extend_warnings(["conversation_context_active"])
        verdict.mark(HardInvariant.CONVERSATION_CONTEXT)

    def enforce_evidence_sufficiency(
        self,
        *,
        question: str,
        evidence: Sequence[RetrievedEvidence],
        pinned_document_ids: Sequence[UUID],
        context_label: str,
        expanded: bool,
        verdict: InvariantVerdict,
    ) -> EvidenceSufficiency:
        """Invariant 4 — classify sufficiency; block with consent offer when pinned miss."""
        assessment = assess_evidence(question=question, evidence=evidence)
        verdict.extend_warnings(assessment.warnings)
        verdict.mark(HardInvariant.EVIDENCE_SUFFICIENCY)

        # Hard block only when the pinned scope returns no evidence at all.
        # Weak-score insufficiency still flows to generation (may abstain + offer).
        if not evidence and pinned_document_ids and not expanded:
            verdict.blocked = True
            verdict.block_answer = build_scope_miss_message(context_label)
            verdict.extend_warnings([AWAITING_SCOPE_EXPAND, "weak_evidence"])
        return assessment.sufficiency

    def enforce_grounded_generation(
        self,
        *,
        question: str,
        answer: str,
        evidence: Sequence[RetrievedEvidence],
        cross_document_authorized: bool,
        pinned_document_ids: Sequence[UUID],
        verdict: InvariantVerdict,
    ) -> str:
        """Invariant 1 — claims must stay within retrieved evidence fidelity."""
        final, extra = finalize_grounded_answer(
            question=question,
            answer=answer,
            evidence=evidence,
            warnings=verdict.warnings,
            cross_document_authorized=cross_document_authorized,
            pinned_document_ids=pinned_document_ids,
        )
        verdict.warnings = list(dict.fromkeys(extra))
        verdict.mark(HardInvariant.GROUNDED_GENERATION)
        verdict.answer = final
        return final

    def enforce_citation_traceability(
        self,
        *,
        answer: str,
        citation_count: int,
        citation_warnings: Sequence[str],
        verdict: InvariantVerdict,
    ) -> None:
        """Invariant 5 — factual answers keep valid citations when evidence exists."""
        from enterprise_rag.domain.citations.validation import is_insufficient_evidence_answer

        verdict.extend_warnings(citation_warnings)
        looks_like_abstain = (
            is_insufficient_evidence_answer(answer)
            or "no relevant information was found" in answer.casefold()
            or "could not find enough retrieved evidence" in answer.casefold()
            or AWAITING_SCOPE_EXPAND in verdict.warnings
        )
        if citation_count == 0 and not looks_like_abstain and answer.strip():
            verdict.extend_warnings(["answer_missing_citations"])
        verdict.mark(HardInvariant.CITATION_TRACEABILITY)
