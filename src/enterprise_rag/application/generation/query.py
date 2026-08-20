"""End-to-end grounded query: contextualize, retrieve, then generate."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from uuid import UUID

from enterprise_rag.application.generation.generate_answer import (
    GenerateAnswerResult,
    GenerateAnswerService,
)
from enterprise_rag.application.retrieval.retrieve import (
    RetrieveEvidenceResult,
    RetrieveEvidenceService,
)
from enterprise_rag.domain.conversation import (
    ConversationTurn,
    QueryContextResolver,
    ResolvedQueryContext,
)
from enterprise_rag.domain.conversation.conversation_context import (
    ActiveConversationContext,
    dominant_document_ids_from_citations,
    infer_context_entities,
    label_for_documents,
    match_document_ids_for_entities,
    normalize_title,
)
from enterprise_rag.domain.conversation.entity_clarification import (
    AWAITING_ENTITY_CLARIFICATION,
    bind_entity_to_question,
    detect_clarification_resume,
)
from enterprise_rag.domain.conversation.scope_expand import (
    AWAITING_SCOPE_EXPAND,
    ScopeExpandDecision,
    answer_looks_like_abstention,
    build_scope_miss_message,
    detect_scope_expand_from_history,
    is_scope_expand_affirmative,
)
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.policies import HardInvariantGate, InvariantVerdict
from enterprise_rag.domain.policies.hard_invariants import HardInvariant
from enterprise_rag.domain.retrieval.models import (
    QueryRequest,
    QueryResponse,
    RetrievalFilters,
    RetrievalRequest,
)
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)

DocumentTitlesProvider = Callable[[TenantContext], Awaitable[Mapping[UUID, str]]]


@dataclass
class QueryDocumentsResult:
    """Combined retrieval + grounded generation outcome."""

    response: QueryResponse
    retrieval: RetrieveEvidenceResult | None
    generation: GenerateAnswerResult | None
    context: ResolvedQueryContext | None = None


class QueryDocumentsService:
    """Application facade for grounded Q&A under hard system invariants."""

    def __init__(
        self,
        retrieve_service: RetrieveEvidenceService,
        generate_service: GenerateAnswerService,
        context_resolver: QueryContextResolver | None = None,
        document_titles: DocumentTitlesProvider | None = None,
        invariant_gate: HardInvariantGate | None = None,
    ) -> None:
        self._retrieve = retrieve_service
        self._generate = generate_service
        self._context_resolver = context_resolver or QueryContextResolver()
        self._document_titles = document_titles
        self._gate = invariant_gate or HardInvariantGate()

    async def query(
        self,
        tenant: TenantContext,
        request: QueryRequest,
    ) -> QueryDocumentsResult:
        verdict = InvariantVerdict()
        self._gate.enforce_security(tenant, verdict)
        if verdict.blocked:
            response = QueryResponse(
                answer=verdict.block_answer or "Unauthorized.",
                retrieval_mode=request.mode,
                citations=[],
                retrieval_trace_id=new_id(),
                warnings=list(verdict.warnings),
                graph_paths=[],
                enforced_invariants=list(verdict.enforced),
            )
            return QueryDocumentsResult(
                response=response,
                retrieval=None,
                generation=None,
                context=None,
            )

        working = request
        titles = await self._load_titles(tenant)

        expand = detect_scope_expand_from_history(
            question=request.question,
            conversation_history=list(request.conversation_history),
        )
        if request.expand_document_scope:
            prior = expand.prior_question
            if prior is None and not is_scope_expand_affirmative(request.question):
                prior = request.question
            expand = ScopeExpandDecision(expand=True, prior_question=prior)

        expanded = False
        if expand.expand:
            replay = expand.prior_question
            if replay and not is_scope_expand_affirmative(replay):
                working = request.model_copy(
                    update={
                        "question": replay,
                        "filters": RetrievalFilters(
                            document_ids=[],
                            modalities=list(request.filters.modalities),
                            tags=list(request.filters.tags),
                            security_labels=list(request.filters.security_labels),
                        ),
                    }
                )
                expanded = True
                logger.info("document_scope_expanded", prior_question=replay[:120])

        # Resume pending question after "Which entity…?" clarification replies.
        clarification_resume = detect_clarification_resume(
            question=working.question,
            conversation_history=list(working.conversation_history),
        )
        if clarification_resume is not None:
            resumed = bind_entity_to_question(
                clarification_resume.pending_question,
                clarification_resume.selected_entity,
            )
            working = working.model_copy(update={"question": resumed})
            verdict.extend_warnings(["entity_clarification_resumed"])
            logger.info(
                "entity_clarification_resumed",
                entity=clarification_resume.selected_entity,
                pending=clarification_resume.pending_question[:120],
            )

        # Infer sticky document pin BEFORE clarification so follow-ups keep scope
        # even when the client only has a label (empty document_ids).
        history = list(working.conversation_history)
        early_entities = [
            item
            for item in infer_context_entities(
                working.question, history, self._context_resolver
            )
            if item.casefold() not in {"who", "what", "when", "where", "why", "how"}
        ]
        if (
            not expanded
            and not working.filters.document_ids
            and history
            and early_entities
        ):
            sticky = match_document_ids_for_entities(early_entities, titles)
            if sticky:
                working = working.model_copy(
                    update={
                        "filters": RetrievalFilters(
                            document_ids=list(sticky),
                            modalities=list(working.filters.modalities),
                            tags=list(working.filters.tags),
                            security_labels=list(working.filters.security_labels),
                        )
                    }
                )
                verdict.extend_warnings(["document_scope_inferred_before_clarify"])

        context = self._resolve_context(
            working,
            known_entities=early_entities or None,
        )
        if context.ambiguous and context.clarification_question:
            pinned_for_clarify = list(working.filters.document_ids)
            # Single pinned document already defines scope — don't derail the Q.
            if len(pinned_for_clarify) == 1:
                title = titles.get(pinned_for_clarify[0], "")
                title_norm = normalize_title(title).casefold()
                preferred = [
                    entity
                    for entity in context.active_entities
                    if entity.casefold() not in {"who", "what", "when", "where", "why", "how"}
                    and (
                        entity.casefold() in title_norm
                        or title_norm in entity.casefold()
                        or entity.casefold() in title.casefold()
                    )
                ]
                chosen = preferred[0] if preferred else (
                    normalize_title(title) if title else None
                )
                if chosen:
                    bound = bind_entity_to_question(working.question, chosen)
                    working = working.model_copy(update={"question": bound})
                    context = self._resolve_context(
                        working,
                        known_entities=[chosen],
                    )
                    verdict.extend_warnings(["ambiguous_reference_resolved_by_document_pin"])
                else:
                    context = context.model_copy(
                        update={
                            "ambiguous": False,
                            "clarification_question": None,
                        }
                    )
                    verdict.extend_warnings(["ambiguous_reference_skipped_document_pin"])
            elif early_entities:
                # Active conversation already has one product entity — keep it.
                unique = list(dict.fromkeys(early_entities))
                if len(unique) == 1:
                    bound = bind_entity_to_question(working.question, unique[0])
                    working = working.model_copy(update={"question": bound})
                    context = self._resolve_context(
                        working,
                        known_entities=unique,
                    )
                    verdict.extend_warnings(["ambiguous_reference_resolved_by_active_entity"])

        if context.ambiguous and context.clarification_question:
            verdict.extend_warnings(
                [
                    *context.warnings,
                    "ambiguous_reference",
                    AWAITING_ENTITY_CLARIFICATION,
                ]
            )
            self._gate.enforce_conversation_context(
                has_active_context=bool(working.filters.document_ids)
                or bool(working.conversation_history),
                context_switch=False,
                inferred=False,
                verdict=verdict,
            )
            self._gate.enforce_retrieval_scope(
                pinned_document_ids=list(working.filters.document_ids),
                expanded=expanded,
                verdict=verdict,
            )
            response = QueryResponse(
                answer=context.clarification_question,
                retrieval_mode=working.mode,
                citations=[],
                retrieval_trace_id=new_id(),
                warnings=list(verdict.warnings),
                graph_paths=[],
                enforced_invariants=list(verdict.enforced),
                active_conversation_context=self._build_active_context(
                    pinned_ids=list(working.filters.document_ids),
                    titles=titles,
                    entities=list(context.active_entities),
                    citations=[],
                ).model_dump(mode="json")
                if working.filters.document_ids or context.active_entities
                else None,
            )
            return QueryDocumentsResult(
                response=response,
                retrieval=None,
                generation=None,
                context=context,
            )

        # Sticky conversation pin for FOLLOW-UPS only.
        # First turn may search openly; the first answer confirms/establishes context.
        pinned_ids = list(working.filters.document_ids)
        history = list(working.conversation_history)
        entities = infer_context_entities(
            working.question,
            history,
            self._context_resolver,
        )
        entities = [
            item
            for item in entities
            if item.casefold() not in {"who", "what", "when", "where", "why", "how"}
        ]
        has_prior_turns = bool(history)
        inferred_pin = False
        if context.context_switch:
            entities = list(context.active_entities) or entities
            entities = [
                item
                for item in entities
                if item.casefold() not in {"who", "what", "when", "where", "why", "how"}
            ]
            pinned_ids = match_document_ids_for_entities(entities, titles)
        elif not expanded and not pinned_ids and has_prior_turns:
            pinned_ids = match_document_ids_for_entities(entities, titles)
            inferred_pin = bool(pinned_ids)
        elif not expanded and not pinned_ids and not has_prior_turns and entities:
            # First turn, no history to be ambiguous about — but if the question
            # names exactly one document unambiguously (e.g. "EMULGEN 2020G"),
            # pin retrieval to it instead of "searching openly". An open search
            # lets a short/sparse document lose to an unrelated, richer-embedded
            # one on generic terms like "composition" — active_conversation_context
            # already resolves this same entity match for display; retrieval was
            # silently not using it. Stay open (no pin) whenever the match is
            # ambiguous (0 or 2+ documents), preserving today's behavior there.
            first_turn_match = match_document_ids_for_entities(entities, titles)
            if len(first_turn_match) == 1:
                pinned_ids = first_turn_match
                inferred_pin = True

        self._gate.enforce_conversation_context(
            has_active_context=bool(pinned_ids) or has_prior_turns,
            context_switch=context.context_switch,
            inferred=inferred_pin,
            verdict=verdict,
        )

        if pinned_ids and not expanded:
            working = working.model_copy(
                update={
                    "filters": RetrievalFilters(
                        document_ids=list(pinned_ids),
                        modalities=list(working.filters.modalities),
                        tags=list(working.filters.tags),
                        security_labels=list(working.filters.security_labels),
                    )
                }
            )

        self._gate.enforce_retrieval_scope(
            pinned_document_ids=list(working.filters.document_ids),
            expanded=expanded,
            verdict=verdict,
        )

        retrieval_question = context.resolved_query
        if (
            not expanded
            and has_prior_turns
            and entities
            and entities[0].casefold() not in retrieval_question.casefold()
            and (context.requires_history or has_prior_turns)
        ):
            retrieval_question = f"{retrieval_question.rstrip('?')} for {entities[0]}?"

        retrieval = await self._retrieve.retrieve(
            tenant,
            RetrievalRequest(
                question=retrieval_question,
                mode=working.mode,
                filters=working.filters,
                top_k=working.top_k,
                graph_depth=working.graph_depth,
                include_graph_paths=working.include_graph_paths,
                rerank=working.rerank,
            ),
        )
        verdict.extend_warnings(retrieval.result.warnings)

        active = self._build_active_context(
            pinned_ids=list(working.filters.document_ids),
            titles=titles,
            entities=entities,
            citations=[],
        )
        label = active.label if active else label_for_documents(
            list(working.filters.document_ids), titles, entities=entities
        )

        self._gate.enforce_evidence_sufficiency(
            question=retrieval_question,
            evidence=retrieval.result.evidence,
            pinned_document_ids=list(working.filters.document_ids),
            context_label=label,
            expanded=expanded,
            verdict=verdict,
        )
        if verdict.blocked:
            response = QueryResponse(
                answer=verdict.block_answer or build_scope_miss_message(label),
                retrieval_mode=retrieval.result.mode,
                citations=[],
                retrieval_trace_id=retrieval.result.retrieval_trace_id,
                warnings=list(verdict.warnings),
                graph_paths=[],
                active_conversation_context=active.model_dump(mode="json") if active else None,
                enforced_invariants=list(verdict.enforced),
            )
            return QueryDocumentsResult(
                response=response,
                retrieval=retrieval,
                generation=None,
                context=context,
            )

        generation = await self._generate.generate(
            tenant,
            question=retrieval_question,
            retrieval=retrieval.result,
            answer_model_override=working.answer_model_override,
        )
        verdict.extend_warnings(generation.response.warnings)
        if context.requires_history:
            verdict.extend_warnings(["history_resolved"])
        verdict.extend_warnings(context.warnings)

        answer = generation.response.answer
        if (
            working.filters.document_ids
            and not expanded
            and ("weak_evidence" in verdict.warnings or answer_looks_like_abstention(answer))
        ):
            offer = build_scope_miss_message(label)
            if offer not in answer:
                answer = f"{answer.rstrip()}\n\n{offer}"
            verdict.extend_warnings([AWAITING_SCOPE_EXPAND])

        if not active or not active.document_ids:
            cited = dominant_document_ids_from_citations(generation.response.citations)
            active = self._build_active_context(
                pinned_ids=cited or list(working.filters.document_ids),
                titles=titles,
                entities=entities,
                citations=generation.response.citations,
            )
        if expanded and generation.response.citations:
            if entities:
                sticky = match_document_ids_for_entities(entities, titles)
                if sticky:
                    active = self._build_active_context(
                        pinned_ids=sticky,
                        titles=titles,
                        entities=entities,
                        citations=[],
                    )
            verdict.extend_warnings(["cross_document_answer"])

        answer = self._gate.enforce_grounded_generation(
            question=retrieval_question,
            answer=answer,
            evidence=retrieval.result.evidence,
            cross_document_authorized=expanded,
            pinned_document_ids=list(working.filters.document_ids) if not expanded else [],
            verdict=verdict,
        )
        self._gate.enforce_citation_traceability(
            answer=answer,
            citation_count=len(generation.response.citations),
            citation_warnings=[],
            verdict=verdict,
        )
        # First-turn open search still establishes conversation context after answer.
        if not has_prior_turns:
            verdict.mark(HardInvariant.CONVERSATION_CONTEXT)

        response = generation.response.model_copy(
            update={
                "answer": answer,
                "warnings": list(dict.fromkeys(verdict.warnings)),
                "active_conversation_context": (
                    active.model_dump(mode="json") if active else None
                ),
                "enforced_invariants": list(verdict.enforced),
            }
        )
        logger.info(
            "query_completed",
            mode=response.retrieval_mode.value,
            evidence=len(retrieval.result.evidence),
            citations=len(response.citations),
            trace_id=str(response.retrieval_trace_id),
            context_switch=context.context_switch,
            resolved_query=context.resolved_query[:120],
            awaiting_scope_expand=AWAITING_SCOPE_EXPAND in verdict.warnings,
            active_context=active.label if active else None,
            enforced_invariants=response.enforced_invariants,
        )
        return QueryDocumentsResult(
            response=response,
            retrieval=retrieval,
            generation=generation,
            context=context,
        )

    async def _load_titles(self, tenant: TenantContext) -> dict[UUID, str]:
        if self._document_titles is None:
            return {}
        return dict(await self._document_titles(tenant))

    def _build_active_context(
        self,
        *,
        pinned_ids: list[UUID],
        titles: dict[UUID, str],
        entities: list[str],
        citations: list[object],
    ) -> ActiveConversationContext | None:
        doc_ids = list(pinned_ids)
        if not doc_ids and citations:
            doc_ids = dominant_document_ids_from_citations(citations)
        # Label-only context (entities without ids) breaks follow-up pins in the UI.
        if not doc_ids and entities:
            doc_ids = match_document_ids_for_entities(entities, titles)
        if not doc_ids and not entities:
            return None
        label = label_for_documents(doc_ids, titles, entities=entities)
        return ActiveConversationContext(
            label=label,
            document_ids=doc_ids,
            entities=list(entities[:3]),
        )

    def _resolve_context(
        self,
        request: QueryRequest,
        *,
        known_entities: list[str] | None = None,
    ) -> ResolvedQueryContext:
        history = [
            ConversationTurn(role=str(item.get("role", "user")), content=str(item["content"]))
            for item in request.conversation_history
            if item.get("content")
        ]
        return self._context_resolver.resolve(
            request.question,
            history,
            known_entities=known_entities,
        )
