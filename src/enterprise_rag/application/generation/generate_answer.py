"""Grounded answer generation with citation validation."""

from __future__ import annotations

from dataclasses import dataclass, field

from enterprise_rag.application.generation.prompts import (
    PROMPT_VERSION,
    build_answer_messages,
)
from enterprise_rag.domain.citations.parsing import parse_generation_text
from enterprise_rag.domain.citations.registry import CitationRegistry
from enterprise_rag.domain.citations.validation import (
    CitationValidationResult,
    remap_graph_path_citations,
    validate_citations,
)
from enterprise_rag.domain.generation.claim_fidelity import (
    CLAIM_STRENGTH_OVERREACH,
    detect_claim_strength_overreach,
    soften_normative_overreach,
)
from enterprise_rag.domain.generation.grounding_policy import (
    assess_evidence,
    filter_grounded_graph_paths,
    finalize_grounded_answer,
)
from enterprise_rag.domain.models.contracts import GenerationRequest, ModelRole
from enterprise_rag.domain.models.protocols import ChatModel
from enterprise_rag.domain.retrieval.models import (
    QueryResponse,
    RetrievalResult,
)
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import CitationValidationError
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)


@dataclass
class GenerateAnswerResult:
    """Grounded answer plus validation metadata."""

    response: QueryResponse
    registry: CitationRegistry
    validation: CitationValidationResult
    retried: bool = False
    model_warnings: list[str] = field(default_factory=list)


class GenerateAnswerService:
    """Generate an answer from retrieved evidence and validate citations."""

    def __init__(
        self,
        chat_model: ChatModel,
        *,
        max_retries: int = 1,
        temperature: float = 0.0,
    ) -> None:
        self._chat = chat_model
        self._max_retries = max(0, max_retries)
        self._temperature = temperature

    async def generate(
        self,
        tenant: TenantContext,
        *,
        question: str,
        retrieval: RetrievalResult,
        answer_model_override: str | None = None,
    ) -> GenerateAnswerResult:
        registry = CitationRegistry(tenant, retrieval.evidence)
        warnings = list(retrieval.warnings)
        assessment = assess_evidence(question=question, evidence=retrieval.evidence)
        warnings.extend(assessment.warnings)

        if not retrieval.evidence:
            warnings.append("weak_evidence")
            response = QueryResponse(
                answer=(
                    "I could not find enough retrieved evidence to answer "
                    "this question grounded in sources."
                ),
                retrieval_mode=retrieval.mode,
                citations=[],
                retrieval_trace_id=retrieval.retrieval_trace_id,
                warnings=list(dict.fromkeys(warnings)),
                graph_paths=[],
            )
            empty_validation = validate_citations(
                tenant=tenant,
                answer=response.answer,
                registry=registry,
                claimed_ids=[],
                strict=False,
            )
            return GenerateAnswerResult(
                response=response,
                registry=registry,
                validation=empty_validation,
            )

        parsed_answer, claimed_ids, model_warnings, retried = await self._generate_with_retry(
            tenant=tenant,
            question=question,
            retrieval=retrieval,
            registry=registry,
            answer_model_override=answer_model_override,
        )
        warnings.extend(model_warnings)

        validation = validate_citations(
            tenant=tenant,
            answer=parsed_answer,
            registry=registry,
            claimed_ids=claimed_ids,
            strict=False,
        )
        warnings.extend(validation.warnings)

        evidence_texts = [item.text for item in retrieval.evidence if item.text]
        if detect_claim_strength_overreach(question, validation.answer, evidence_texts):
            warnings.append(CLAIM_STRENGTH_OVERREACH)
            softened = soften_normative_overreach(validation.answer)
            if softened != validation.answer:
                validation = validate_citations(
                    tenant=tenant,
                    answer=softened,
                    registry=registry,
                    claimed_ids=claimed_ids,
                    strict=False,
                )
                warnings.extend(validation.warnings)

        if not validation.valid:
            from enterprise_rag.infrastructure.observability import get_metrics

            get_metrics().incr("citation_validation_failures_total")

        evidence_chunk_ids = {item.chunk_id for item in retrieval.evidence}
        graph_paths, path_warnings = filter_grounded_graph_paths(
            retrieval.graph_paths,
            evidence_chunk_ids=evidence_chunk_ids,
        )
        warnings.extend(path_warnings)
        graph_paths = remap_graph_path_citations(graph_paths, registry)
        citations = validation.citations

        final_answer, final_warnings = finalize_grounded_answer(
            question=question,
            answer=validation.answer,
            evidence=retrieval.evidence,
            warnings=warnings,
            cross_document_authorized=False,
            pinned_document_ids=[],
        )

        response = QueryResponse(
            answer=final_answer,
            retrieval_mode=retrieval.mode,
            citations=citations,
            retrieval_trace_id=retrieval.retrieval_trace_id,
            warnings=list(dict.fromkeys(final_warnings)),
            graph_paths=graph_paths,
        )
        logger.info(
            "answer_generated",
            mode=retrieval.mode.value,
            citations=len(citations),
            retried=retried,
            sufficiency=assessment.sufficiency.value,
            trace_id=str(retrieval.retrieval_trace_id),
        )
        return GenerateAnswerResult(
            response=response,
            registry=registry,
            validation=validation,
            retried=retried,
            model_warnings=model_warnings,
        )

    async def _generate_with_retry(
        self,
        *,
        tenant: TenantContext,
        question: str,
        retrieval: RetrievalResult,
        registry: CitationRegistry,
        answer_model_override: str | None,
    ) -> tuple[str, list[str], list[str], bool]:
        retried = False
        model_warnings: list[str] = []
        answer = ""
        claimed: list[str] = []

        for attempt in range(self._max_retries + 1):
            strict_retry = attempt > 0
            retried = strict_retry
            messages = build_answer_messages(
                question=question,
                mode=retrieval.mode,
                registry=registry,
                graph_paths=retrieval.graph_paths,
                strict_retry=strict_retry,
                allowed_ids=registry.ids(),
                evidence=retrieval.evidence,
            )
            generation = await self._chat.generate(
                GenerationRequest(
                    messages=messages,
                    role=ModelRole.ANSWER,
                    model_name=answer_model_override,
                    temperature=self._temperature,
                    prompt_version=PROMPT_VERSION,
                    metadata={
                        "retrieval_trace_id": str(retrieval.retrieval_trace_id),
                        "allowed_citation_ids": list(registry.ids()),
                        "attempt": attempt,
                    },
                )
            )
            parsed = parse_generation_text(generation.text)
            model_warnings.extend(parsed.warnings)
            answer = parsed.answer
            claimed = parsed.citation_ids

            evidence_texts = [item.text for item in retrieval.evidence if item.text]
            overreach = detect_claim_strength_overreach(question, answer, evidence_texts)

            try:
                validation = validate_citations(
                    tenant=tenant,
                    answer=answer,
                    registry=registry,
                    claimed_ids=claimed,
                    strict=True,
                )
                if overreach and attempt < self._max_retries:
                    logger.warning(
                        "claim_strength_overreach_retry",
                        attempt=attempt,
                        question=question[:120],
                    )
                    model_warnings.append(CLAIM_STRENGTH_OVERREACH)
                    continue
                return validation.answer, validation.cited_ids, model_warnings, retried
            except CitationValidationError as exc:
                logger.warning(
                    "citation_validation_retry",
                    attempt=attempt,
                    error=str(exc),
                    details=exc.details,
                )
                if attempt >= self._max_retries:
                    # Fall through to non-strict handling in caller.
                    return answer, claimed, model_warnings, retried
                continue

        return answer, claimed, model_warnings, retried
