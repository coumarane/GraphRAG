"""End-to-end grounded query: contextualize, retrieve, then generate."""

from __future__ import annotations

from dataclasses import dataclass

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
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.retrieval.models import (
    QueryRequest,
    QueryResponse,
    RetrievalRequest,
)
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)


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
    ) -> None:
        self._retrieve = retrieve_service
        self._generate = generate_service
        self._context_resolver = context_resolver or QueryContextResolver()

    async def query(
        self,
        tenant: TenantContext,
        request: QueryRequest,
    ) -> QueryDocumentsResult:
        context = self._resolve_context(request)
        if context.ambiguous and context.clarification_question:
            response = QueryResponse(
                answer=context.clarification_question,
                retrieval_mode=request.mode,
                citations=[],
                retrieval_trace_id=new_id(),
                warnings=[*context.warnings, "ambiguous_reference"],
                graph_paths=[],
            )
            logger.info(
                "query_clarification_required",
                context_switch=context.context_switch,
                active_entities=context.active_entities,
            )
            return QueryDocumentsResult(
                response=response,
                retrieval=None,
                generation=None,
                context=context,
            )

        retrieval_question = context.resolved_query
        retrieval = await self._retrieve.retrieve(
            tenant,
            RetrievalRequest(
                question=retrieval_question,
                mode=request.mode,
                filters=request.filters,
                top_k=request.top_k,
                graph_depth=request.graph_depth,
                include_graph_paths=request.include_graph_paths,
                rerank=request.rerank,
            ),
        )
        generation = await self._generate.generate(
            tenant,
            question=retrieval_question,
            retrieval=retrieval.result,
            answer_model_override=request.answer_model_override,
        )
        warnings = list(generation.response.warnings)
        if context.context_switch:
            warnings.append("context_switch_detected")
        if context.requires_history:
            warnings.append("history_resolved")
        for warning in context.warnings:
            if warning not in warnings:
                warnings.append(warning)
        response = generation.response.model_copy(update={"warnings": warnings})
        logger.info(
            "query_completed",
            mode=response.retrieval_mode.value,
            evidence=len(retrieval.result.evidence),
            citations=len(response.citations),
            trace_id=str(response.retrieval_trace_id),
            context_switch=context.context_switch,
            resolved_query=context.resolved_query[:120],
        )
        return QueryDocumentsResult(
            response=response,
            retrieval=retrieval,
            generation=generation,
            context=context,
        )

    def _resolve_context(self, request: QueryRequest) -> ResolvedQueryContext:
        history = [
            ConversationTurn(role=str(item.get("role", "user")), content=str(item["content"]))
            for item in request.conversation_history
            if item.get("content")
        ]
        return self._context_resolver.resolve(request.question, history)
