"""Retrieval, query and graph-search routes."""

from __future__ import annotations

from fastapi import APIRouter

from graph_rag.api.dependencies import ContainerDep, TenantDep
from graph_rag.api.schemas import (
    GraphSearchRequest,
    GraphSearchResponse,
    QueryApiRequest,
    QueryApiResponse,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from graph_rag.application.authorization.gate import require_action, reserve_quota
from graph_rag.application.usage.context import usage_context
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.conversation.naming import title_from_question
from graph_rag.domain.conversation.records import ChatConversationRecord, ChatMessageRecord
from graph_rag.domain.ids import new_id
from graph_rag.domain.quotas.models import QuotaMetric, QuotaPeriod
from graph_rag.domain.retrieval.models import (
    QueryRequest,
    QueryResponse,
    RetrievalFilters,
    RetrievalRequest,
)
from graph_rag.shared.exceptions import ConfigurationError

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
    conv_repo = container.require_chat_conversation_repo()

    if body.conversation_id is not None:
        conversation = await conv_repo.get_conversation(tenant, body.conversation_id)
        if conversation is None:
            # Upsert-on-unknown-id: closes a race between the frontend's
            # background "create conversation" call (fired when a new chat
            # starts) and the first message being sent before that call has
            # landed. Simpler and more robust than client-side promise
            # tracking, and no less safe — the id is still tenant/owner
            # scoped from here on.
            conversation = await conv_repo.create_conversation(
                tenant,
                ChatConversationRecord(
                    conversation_id=body.conversation_id,
                    tenant_id=tenant.tenant_id,
                    owner_user_id=tenant.user_id,
                    mode=body.mode.value,
                    interaction_mode=body.interaction_mode,
                ),
            )
    else:
        conversation = await conv_repo.create_conversation(
            tenant,
            ChatConversationRecord(
                conversation_id=new_id(),
                tenant_id=tenant.tenant_id,
                owner_user_id=tenant.user_id,
                mode=body.mode.value,
                interaction_mode=body.interaction_mode,
            ),
        )

    history_records = await conv_repo.list_messages(tenant, conversation.conversation_id)
    history = [{"role": message.role, "content": message.content} for message in history_records]
    # body.conversation_history is intentionally never used from here on: once
    # conversation_id resolves, the server-persisted history is the source of
    # truth. Honoring a client-sent array in parallel would let a client
    # inject fabricated prior turns straight into entity-pinning/clarification
    # prompt construction, and would silently diverge from what's persisted.

    reservation = reserve_quota(
        container.require_quotas(),
        tenant,
        metric=QuotaMetric.QUERIES,
        quantity=1,
        period=QuotaPeriod.DAY,
    )
    try:
        with usage_context(
            tenant_id=tenant.tenant_id,
            query_id=new_id(),
            user_id=tenant.user_id,
        ):
            if body.interaction_mode == "chat":
                chat_result = await container.require_chat().chat(
                    tenant,
                    question=body.question,
                    history=history,
                )
                response = QueryResponse(
                    answer=chat_result.answer,
                    retrieval_mode=None,
                    interaction_mode="chat",
                    citations=[],
                    graph_paths=[],
                    retrieval_trace_id=new_id(),
                    warnings=list(chat_result.warnings),
                )
            else:
                service = container.require_query()
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
                        conversation_history=history,
                        expand_document_scope=body.expand_document_scope,
                    ),
                )
                response = outcome.response
        container.require_quotas().commit(
            reservation_id=reservation.reservation_id,
            actual_quantity=1,
        )
    except Exception:
        container.require_quotas().release(reservation_id=reservation.reservation_id)
        raise

    next_pending = conversation.pending_expand_question
    if body.interaction_mode == "search":
        pending = (conversation.pending_expand_question or "").strip()
        awaiting = "awaiting_scope_expand" in response.warnings
        next_pending = (
            (pending if pending and body.expand_document_scope else body.question)
            if awaiting
            else None
        )

    await conv_repo.add_message(
        tenant,
        ChatMessageRecord(
            message_id=new_id(),
            tenant_id=tenant.tenant_id,
            conversation_id=conversation.conversation_id,
            role="user",
            content=body.question,
            interaction_mode=body.interaction_mode,
        ),
    )
    await conv_repo.add_message(
        tenant,
        ChatMessageRecord(
            message_id=new_id(),
            tenant_id=tenant.tenant_id,
            conversation_id=conversation.conversation_id,
            role="assistant",
            content=response.answer,
            interaction_mode=body.interaction_mode,
            citations=[citation.model_dump(mode="json") for citation in response.citations],
            warnings=list(response.warnings),
            retrieval_mode=response.retrieval_mode.value if response.retrieval_mode else None,
            retrieval_trace_id=response.retrieval_trace_id,
            graph_paths=[path.model_dump(mode="json") for path in response.graph_paths],
        ),
    )

    conversation.interaction_mode = body.interaction_mode
    if body.interaction_mode == "search":
        conversation.pending_expand_question = next_pending
        conversation.conversation_context = response.active_conversation_context
    if not history_records and conversation.title in ("", "New chat"):
        conversation.title = title_from_question(body.question)
    await conv_repo.update_conversation(tenant, conversation)

    await container.commit_db()
    return QueryApiResponse(
        **response.model_dump(),
        conversation_id=conversation.conversation_id,
        pending_expand_question=next_pending,
    )


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

    from graph_rag.application.authorization.gate import authorized_document_ids
    from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus

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
