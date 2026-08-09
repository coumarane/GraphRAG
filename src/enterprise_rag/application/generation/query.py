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
)
from enterprise_rag.domain.conversation.scope_expand import (
    AWAITING_SCOPE_EXPAND,
    DOCUMENT_SCOPE_EXPANDED,
    ScopeExpandDecision,
    answer_looks_like_abstention,
    build_scope_miss_message,
    detect_scope_expand_from_history,
    is_scope_expand_affirmative,
)
from enterprise_rag.domain.ids import new_id
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
    """Application facade for grounded Q&A."""

    def __init__(
        self,
        retrieve_service: RetrieveEvidenceService,
        generate_service: GenerateAnswerService,
        context_resolver: QueryContextResolver | None = None,
        document_titles: DocumentTitlesProvider | None = None,
    ) -> None:
        self._retrieve = retrieve_service
        self._generate = generate_service
        self._context_resolver = context_resolver or QueryContextResolver()
        self._document_titles = document_titles

    async def query(
        self,
        tenant: TenantContext,
        request: QueryRequest,
    ) -> QueryDocumentsResult:
        working = request
        expand_warnings: list[str] = []
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
                expand_warnings.append(DOCUMENT_SCOPE_EXPANDED)
                expanded = True
                logger.info("document_scope_expanded", prior_question=replay[:120])

        context = self._resolve_context(working)
        if context.ambiguous and context.clarification_question:
            response = QueryResponse(
                answer=context.clarification_question,
                retrieval_mode=working.mode,
                citations=[],
                retrieval_trace_id=new_id(),
                warnings=[*context.warnings, "ambiguous_reference", *expand_warnings],
                graph_paths=[],
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
        # Drop interrogative leftovers that sometimes escape entity filters.
        entities = [
            item
            for item in entities
            if item.casefold() not in {"who", "what", "when", "where", "why", "how"}
        ]
        has_prior_turns = bool(history)
        if context.context_switch:
            entities = list(context.active_entities) or entities
            entities = [
                item
                for item in entities
                if item.casefold() not in {"who", "what", "when", "where", "why", "how"}
            ]
            pinned_ids = match_document_ids_for_entities(entities, titles)
            if pinned_ids:
                expand_warnings.append("conversation_context_switched")
        elif not expanded and not pinned_ids and has_prior_turns:
            # Follow-up: stick to docs established by the opening Q/A.
            pinned_ids = match_document_ids_for_entities(entities, titles)
            if pinned_ids:
                expand_warnings.append("conversation_context_inferred")

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

        retrieval_question = context.resolved_query
        # Keep sticky entity in the retrieval question for follow-ups only.
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

        active = self._build_active_context(
            pinned_ids=list(working.filters.document_ids),
            titles=titles,
            entities=entities,
            citations=[],
        )

        if working.filters.document_ids and not retrieval.result.evidence and not expanded:
            label = active.label if active else label_for_documents(
                list(working.filters.document_ids), titles, entities=entities
            )
            response = QueryResponse(
                answer=build_scope_miss_message(label),
                retrieval_mode=retrieval.result.mode,
                citations=[],
                retrieval_trace_id=retrieval.result.retrieval_trace_id,
                warnings=[
                    *retrieval.result.warnings,
                    "weak_evidence",
                    AWAITING_SCOPE_EXPAND,
                    *expand_warnings,
                ],
                graph_paths=[],
                active_conversation_context=active.model_dump(mode="json") if active else None,
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
        warnings = list(generation.response.warnings)
        warnings.extend(expand_warnings)
        if context.context_switch:
            warnings.append("context_switch_detected")
        if context.requires_history:
            warnings.append("history_resolved")
        for warning in context.warnings:
            if warning not in warnings:
                warnings.append(warning)

        answer = generation.response.answer
        if (
            working.filters.document_ids
            and not expanded
            and ("weak_evidence" in warnings or answer_looks_like_abstention(answer))
        ):
            label = active.label if active else label_for_documents(
                list(working.filters.document_ids), titles, entities=entities
            )
            offer = build_scope_miss_message(label)
            if offer not in answer:
                answer = f"{answer.rstrip()}\n\n{offer}"
            if AWAITING_SCOPE_EXPAND not in warnings:
                warnings.append(AWAITING_SCOPE_EXPAND)

        # Establish / refresh active context from pins or citation dominance.
        if not active or not active.document_ids:
            cited = dominant_document_ids_from_citations(generation.response.citations)
            active = self._build_active_context(
                pinned_ids=cited or list(working.filters.document_ids),
                titles=titles,
                entities=entities,
                citations=generation.response.citations,
            )
        if expanded and generation.response.citations:
            # Cross-doc answer: keep original sticky context for next turns if known.
            if entities:
                sticky = match_document_ids_for_entities(entities, titles)
                if sticky:
                    active = self._build_active_context(
                        pinned_ids=sticky,
                        titles=titles,
                        entities=entities,
                        citations=[],
                    )
            warnings.append("cross_document_answer")

        response = generation.response.model_copy(
            update={
                "answer": answer,
                "warnings": warnings,
                "active_conversation_context": (
                    active.model_dump(mode="json") if active else None
                ),
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
            awaiting_scope_expand=AWAITING_SCOPE_EXPAND in warnings,
            active_context=active.label if active else None,
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
        if not doc_ids and not entities:
            return None
        label = label_for_documents(doc_ids, titles, entities=entities)
        return ActiveConversationContext(
            label=label,
            document_ids=doc_ids,
            entities=list(entities[:3]),
        )

    def _resolve_context(self, request: QueryRequest) -> ResolvedQueryContext:
        history = [
            ConversationTurn(role=str(item.get("role", "user")), content=str(item["content"]))
            for item in request.conversation_history
            if item.get("content")
        ]
        return self._context_resolver.resolve(request.question, history)
