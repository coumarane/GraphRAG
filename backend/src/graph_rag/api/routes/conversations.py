"""Chat conversation and project CRUD routes.

Messages are not a top-level resource here: they only exist as a side effect
of asking a question via ``POST /query`` (see ``routes/retrieval.py``), and
are only ever read as part of a conversation's detail view.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from graph_rag.api.dependencies import ContainerDep, TenantDep
from graph_rag.api.schemas import (
    ChatConversationCreateRequest,
    ChatConversationDetailResponse,
    ChatConversationListResponse,
    ChatConversationResponse,
    ChatConversationUpdateRequest,
    ChatMessageResponse,
    ChatProjectCreateRequest,
    ChatProjectResponse,
    ChatProjectUpdateRequest,
)
from graph_rag.application.authorization.gate import require_action
from graph_rag.domain.authorization.models import Action
from graph_rag.domain.conversation.records import ChatConversationRecord, ChatProjectRecord
from graph_rag.domain.ids import new_id
from graph_rag.shared.exceptions import NotFoundError, ValidationError

router = APIRouter(prefix="/conversations", tags=["conversations"])
projects_router = APIRouter(prefix="/chat-projects", tags=["chat-projects"])


def _conversation_response(record: ChatConversationRecord) -> ChatConversationResponse:
    return ChatConversationResponse(
        conversation_id=record.conversation_id,
        project_id=record.project_id,
        title=record.title,
        mode=record.mode,
        interaction_mode=record.interaction_mode,
        document_id=record.document_id,
        pending_expand_question=record.pending_expand_question,
        conversation_context=record.conversation_context,
        pinned=record.pinned,
        archived=record.archived,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _project_response(record: ChatProjectRecord) -> ChatProjectResponse:
    return ChatProjectResponse(
        project_id=record.project_id,
        name=record.name,
        pinned=record.pinned,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("", response_model=ChatConversationListResponse)
async def list_conversations(
    tenant: TenantDep,
    container: ContainerDep,
    project_id: UUID | None = None,
    archived: bool | None = None,
    offset: int = 0,
    limit: int = 50,
) -> ChatConversationListResponse:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")
    items, total = await container.require_chat_conversation_repo().list_conversations(
        tenant, project_id=project_id, archived=archived, offset=offset, limit=limit
    )
    return ChatConversationListResponse(
        items=[_conversation_response(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{conversation_id}", response_model=ChatConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> ChatConversationDetailResponse:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    repo = container.require_chat_conversation_repo()
    conversation = await repo.get_conversation(tenant, conversation_id)
    if conversation is None:
        raise NotFoundError(
            "Conversation not found", details={"conversation_id": str(conversation_id)}
        )
    messages = await repo.list_messages(tenant, conversation_id)
    return ChatConversationDetailResponse(
        **_conversation_response(conversation).model_dump(),
        messages=[
            ChatMessageResponse(
                message_id=message.message_id,
                role=message.role,
                content=message.content,
                interaction_mode=message.interaction_mode,
                citations=message.citations,
                warnings=message.warnings,
                retrieval_mode=message.retrieval_mode,
                retrieval_trace_id=message.retrieval_trace_id,
                graph_paths=message.graph_paths,
                created_at=message.created_at,
            )
            for message in messages
        ],
    )


@router.post("", status_code=201, response_model=ChatConversationResponse)
async def create_conversation(
    body: ChatConversationCreateRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> ChatConversationResponse:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    repo = container.require_chat_conversation_repo()
    created = await repo.create_conversation(
        tenant,
        ChatConversationRecord(
            conversation_id=body.conversation_id or new_id(),
            tenant_id=tenant.tenant_id,
            owner_user_id=tenant.user_id,
            project_id=body.project_id,
            title=body.title or "New chat",
            mode=body.mode,
            interaction_mode=body.interaction_mode,
            document_id=body.document_id,
        ),
    )
    await container.commit_db()
    return _conversation_response(created)


@router.patch("/{conversation_id}", response_model=ChatConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    body: ChatConversationUpdateRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> ChatConversationResponse:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    repo = container.require_chat_conversation_repo()
    conversation = await repo.get_conversation(tenant, conversation_id)
    if conversation is None:
        raise NotFoundError(
            "Conversation not found", details={"conversation_id": str(conversation_id)}
        )
    updates = body.model_dump(exclude_unset=True)
    updated = conversation.model_copy(update=updates)
    saved = await repo.update_conversation(tenant, updated)
    await container.commit_db()
    return _conversation_response(saved)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> None:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    await container.require_chat_conversation_repo().delete_conversation(tenant, conversation_id)
    await container.commit_db()


@projects_router.get("", response_model=list[ChatProjectResponse])
async def list_chat_projects(
    tenant: TenantDep,
    container: ContainerDep,
) -> list[ChatProjectResponse]:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    items, _total = await container.require_chat_project_repo().list_projects(
        tenant, offset=0, limit=500
    )
    return [_project_response(item) for item in items]


@projects_router.post("", status_code=201, response_model=ChatProjectResponse)
async def create_chat_project(
    body: ChatProjectCreateRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> ChatProjectResponse:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    created = await container.require_chat_project_repo().create_project(
        tenant,
        ChatProjectRecord(
            project_id=body.project_id or new_id(),
            tenant_id=tenant.tenant_id,
            owner_user_id=tenant.user_id,
            name=body.name,
        ),
    )
    await container.commit_db()
    return _project_response(created)


@projects_router.patch("/{project_id}", response_model=ChatProjectResponse)
async def update_chat_project(
    project_id: UUID,
    body: ChatProjectUpdateRequest,
    tenant: TenantDep,
    container: ContainerDep,
) -> ChatProjectResponse:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    repo = container.require_chat_project_repo()
    project = await repo.get_project(tenant, project_id)
    if project is None:
        raise NotFoundError("Chat project not found", details={"project_id": str(project_id)})
    updates = body.model_dump(exclude_unset=True)
    updated = project.model_copy(update=updates)
    saved = await repo.update_project(tenant, updated)
    await container.commit_db()
    return _project_response(saved)


@projects_router.delete("/{project_id}", status_code=204)
async def delete_chat_project(
    project_id: UUID,
    tenant: TenantDep,
    container: ContainerDep,
) -> None:
    require_action(container.require_authorization(), tenant, Action.QUERY_EXECUTE)
    await container.require_chat_project_repo().delete_project(tenant, project_id)
    await container.commit_db()
