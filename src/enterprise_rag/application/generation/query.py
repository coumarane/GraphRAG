"""End-to-end grounded query: retrieve then generate."""

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
    retrieval: RetrieveEvidenceResult
    generation: GenerateAnswerResult


class QueryDocumentsService:
    """Application facade for grounded Q&A."""

    def __init__(
        self,
        retrieve_service: RetrieveEvidenceService,
        generate_service: GenerateAnswerService,
    ) -> None:
        self._retrieve = retrieve_service
        self._generate = generate_service

    async def query(
        self,
        tenant: TenantContext,
        request: QueryRequest,
    ) -> QueryDocumentsResult:
        retrieval = await self._retrieve.retrieve(
            tenant,
            RetrievalRequest(
                question=request.question,
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
            question=request.question,
            retrieval=retrieval.result,
            answer_model_override=request.answer_model_override,
        )
        logger.info(
            "query_completed",
            mode=generation.response.retrieval_mode.value,
            evidence=len(retrieval.result.evidence),
            citations=len(generation.response.citations),
            trace_id=str(generation.response.retrieval_trace_id),
        )
        return QueryDocumentsResult(
            response=generation.response,
            retrieval=retrieval,
            generation=generation,
        )
