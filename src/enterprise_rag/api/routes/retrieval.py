"""Retrieval, query and graph-search routes."""

from __future__ import annotations

from fastapi import APIRouter

from enterprise_rag.api.dependencies import ContainerDep, TenantDep
from enterprise_rag.api.schemas import (
    GraphSearchRequest,
    GraphSearchResponse,
    QueryApiRequest,
    QueryApiResponse,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from enterprise_rag.application.authorization.gate import require_action, reserve_quota
from enterprise_rag.application.usage.context import usage_context
from enterprise_rag.domain.authorization.models import Action
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.quotas.models import QuotaMetric, QuotaPeriod
from enterprise_rag.domain.retrieval.models import QueryRequest, RetrievalFilters, RetrievalRequest
from enterprise_rag.shared.exceptions import ConfigurationError

router = APIRouter(tags=["retrieval"])


@router.post("/retrieval/search", response_model=RetrievalSearchResponse)
async def retrieval_search(
    body: RetrievalSearchRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> RetrievalSearchResponse:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    reservation = reserve_quota(
        container.require_quotas(),
        tenant,
        metric=QuotaMetric.QUERIES,
        quantity=1,
        period=QuotaPeriod.DAY,
    )
    service = container.require_retrieve()
    try:
        with usage_context(
            tenant_id=tenant.tenant_id,
            query_id=new_id(),
            user_id=tenant.user_id,
        ):
            outcome = await service.retrieve(
                tenant,
                RetrievalRequest(
                    question=body.question,
                    mode=body.mode,
                    filters=RetrievalFilters(
                        document_ids=list(body.document_ids),
                        modalities=list(body.modalities),
                        tags=list(body.tags),
                        security_labels=list(body.security_labels),
                    ),
                    top_k=body.top_k,
                    graph_depth=body.graph_depth,
                    include_graph_paths=body.include_graph_paths,
                    rerank=body.rerank,
                ),
            )
        container.require_quotas().commit(
            reservation_id=reservation.reservation_id,
            actual_quantity=1,
        )
    except Exception:
        container.require_quotas().release(reservation_id=reservation.reservation_id)
        raise
    await container.commit_db()
    result = outcome.result
    return RetrievalSearchResponse(
        mode=result.mode,
        retrieval_trace_id=result.retrieval_trace_id,
        evidence=list(result.evidence),
        graph_paths=list(result.graph_paths),
        warnings=list(result.warnings),
    )


@router.post("/query", response_model=QueryApiResponse)
async def query_documents(
    body: QueryApiRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> QueryApiResponse:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    reservation = reserve_quota(
        container.require_quotas(),
        tenant,
        metric=QuotaMetric.QUERIES,
        quantity=1,
        period=QuotaPeriod.DAY,
    )
    service = container.require_query()
    try:
        with usage_context(
            tenant_id=tenant.tenant_id,
            query_id=new_id(),
            user_id=tenant.user_id,
        ):
            outcome = await service.query(
                tenant,
                QueryRequest(
                    question=body.question,
                    mode=body.mode,
                    filters=RetrievalFilters(
                        document_ids=list(body.document_ids),
                        modalities=list(body.modalities),
                        tags=list(body.tags),
                        security_labels=list(body.security_labels),
                    ),
                    top_k=body.top_k,
                    graph_depth=body.graph_depth,
                    include_graph_paths=body.include_graph_paths,
                    rerank=body.rerank,
                    answer_model_override=body.answer_model_override,
                    conversation_history=list(body.conversation_history),
                    expand_document_scope=body.expand_document_scope,
                ),
            )
        container.require_quotas().commit(
            reservation_id=reservation.reservation_id,
            actual_quantity=1,
        )
    except Exception:
        container.require_quotas().release(reservation_id=reservation.reservation_id)
        raise
    await container.commit_db()
    return outcome.response


@router.post("/graph/search", response_model=GraphSearchResponse)
async def graph_search(
    body: GraphSearchRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> GraphSearchResponse:
    require_action(container.require_authorization(), tenant, Action.GRAPH_QUERY)
    graph = container.graph_store
    if graph is None:
        raise ConfigurationError("Graph store is not configured")

    from enterprise_rag.application.authorization.gate import authorized_document_ids
    from enterprise_rag.domain.ingestion.stages import DocumentLifecycleStatus

    docs, _ = await container.require_document_repo().list_documents(
        tenant, offset=0, limit=500
    )
    allowed_ids = authorized_document_ids(
        container.require_authorization(),
        tenant,
        [d for d in docs if d.status in {DocumentLifecycleStatus.READY, DocumentLifecycleStatus.PARTIAL}],
    )

    entities = await graph.resolve_entities(tenant, names=body.names, limit=body.limit)
    entity_ids = [item.entity_id for item in entities]
    neighbors = (
        await graph.neighborhood(
            tenant,
            seed_node_ids=entity_ids,
            depth=body.depth,
            limit=body.limit,
        )
        if entity_ids
        else []
    )
    find_claims = graph.find_claims
    try:
        claims = (
            await find_claims(
                tenant,
                entity_ids=entity_ids or None,
                document_ids=allowed_ids,
                limit=body.limit,
            )
            if body.include_claims
            else []
        )
    except TypeError:
        claims = (
            await find_claims(tenant, entity_ids=entity_ids or None, limit=body.limit)
            if body.include_claims
            else []
        )
    topics = (
        await graph.find_topics(
            tenant,
            query_terms=body.query_terms or body.names,
            limit=body.limit,
        )
        if body.include_topics
        else []
    )
    node_ids = [
        *entity_ids,
        *[item.node_id for item in neighbors],
        *[item.claim_id for item in claims],
        *[item.topic_id for item in topics],
    ]
    chunk_ids = await graph.chunk_ids_for_nodes(tenant, node_ids=node_ids, limit=body.limit)
    return GraphSearchResponse(
        entities=[item.model_dump(mode="json") for item in entities],
        neighbors=[item.model_dump(mode="json") for item in neighbors],
        claims=[item.model_dump(mode="json") for item in claims],
        topics=[item.model_dump(mode="json") for item in topics],
        chunk_ids=chunk_ids,
    )
