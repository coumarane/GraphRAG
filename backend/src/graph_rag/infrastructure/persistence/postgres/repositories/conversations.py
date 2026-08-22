"""Chat project and conversation repository adapters."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graph_rag.domain.conversation.records import (
    ChatConversationRecord,
    ChatMessageRecord,
    ChatProjectRecord,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.postgres.mappers import (
    chat_conversation_to_record,
    chat_message_to_record,
    chat_project_to_record,
)
from graph_rag.infrastructure.persistence.postgres.models import (
    ChatConversationModel,
    ChatMessageModel,
    ChatProjectModel,
)
from graph_rag.infrastructure.persistence.postgres.rls import (
    require_matching_tenant,
    set_tenant_context,
)
from graph_rag.shared.exceptions import ConflictError, NotFoundError


class SqlAlchemyChatProjectRepository:
    """SQLAlchemy implementation of ``ChatProjectRepository``.

    Read queries use ``populate_existing=True``: the session backing this repo
    is process-lifetime (see runtime.py), so an object already loaded earlier
    — e.g. a conversation fetched before its project was deleted elsewhere in
    the same session — would otherwise keep showing stale attributes (like a
    project_id an ON DELETE SET NULL already cleared) instead of the current
    row.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_project(
        self,
        tenant: TenantContext,
        project: ChatProjectRecord,
    ) -> ChatProjectRecord:
        require_matching_tenant(tenant, project.tenant_id)
        await set_tenant_context(self._session, tenant)
        existing = await self._session.get(ChatProjectModel, project.project_id)
        if existing is not None:
            raise ConflictError("Chat project already exists")
        model = ChatProjectModel(
            project_id=project.project_id,
            tenant_id=project.tenant_id,
            owner_user_id=tenant.user_id,
            name=project.name,
            pinned=project.pinned,
        )
        self._session.add(model)
        await self._session.flush()
        return chat_project_to_record(model)

    async def get_project(
        self,
        tenant: TenantContext,
        project_id: UUID,
    ) -> ChatProjectRecord | None:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(ChatProjectModel)
            .where(
                ChatProjectModel.project_id == project_id,
                ChatProjectModel.tenant_id == tenant.tenant_id,
                ChatProjectModel.owner_user_id == tenant.user_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.scalar_one_or_none()
        return chat_project_to_record(model) if model is not None else None

    async def list_projects(
        self,
        tenant: TenantContext,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[ChatProjectRecord], int]:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        base_clauses = [
            ChatProjectModel.tenant_id == tenant.tenant_id,
            ChatProjectModel.owner_user_id == tenant.user_id,
        ]
        total_result = await self._session.execute(
            select(ChatProjectModel.project_id).where(*base_clauses)
        )
        total = len(list(total_result.scalars().all()))
        result = await self._session.execute(
            select(ChatProjectModel)
            .where(*base_clauses)
            .order_by(ChatProjectModel.updated_at.desc().nullslast())
            .offset(offset)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        models = list(result.scalars().all())
        return [chat_project_to_record(model) for model in models], total

    async def update_project(
        self,
        tenant: TenantContext,
        project: ChatProjectRecord,
    ) -> ChatProjectRecord:
        require_matching_tenant(tenant, project.tenant_id)
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(ChatProjectModel).where(
                ChatProjectModel.project_id == project.project_id,
                ChatProjectModel.tenant_id == tenant.tenant_id,
                ChatProjectModel.owner_user_id == tenant.user_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError(
                "Chat project not found", details={"project_id": str(project.project_id)}
            )
        model.name = project.name
        model.pinned = project.pinned
        await self._session.flush()
        return chat_project_to_record(model)

    async def delete_project(
        self,
        tenant: TenantContext,
        project_id: UUID,
    ) -> None:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(ChatProjectModel).where(
                ChatProjectModel.project_id == project_id,
                ChatProjectModel.tenant_id == tenant.tenant_id,
                ChatProjectModel.owner_user_id == tenant.user_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        await self._session.delete(model)
        await self._session.flush()


class SqlAlchemyChatConversationRepository:
    """SQLAlchemy implementation of ``ChatConversationRepository``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_conversation(
        self,
        tenant: TenantContext,
        conversation: ChatConversationRecord,
    ) -> ChatConversationRecord:
        require_matching_tenant(tenant, conversation.tenant_id)
        await set_tenant_context(self._session, tenant)
        existing = await self._session.get(ChatConversationModel, conversation.conversation_id)
        if existing is not None:
            raise ConflictError("Chat conversation already exists")
        model = ChatConversationModel(
            conversation_id=conversation.conversation_id,
            tenant_id=conversation.tenant_id,
            owner_user_id=tenant.user_id,
            project_id=conversation.project_id,
            title=conversation.title,
            mode=conversation.mode,
            document_id=conversation.document_id,
            pending_expand_question=conversation.pending_expand_question,
            conversation_context=conversation.conversation_context,
            pinned=conversation.pinned,
            archived=conversation.archived,
        )
        self._session.add(model)
        await self._session.flush()
        return chat_conversation_to_record(model)

    async def get_conversation(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
    ) -> ChatConversationRecord | None:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(ChatConversationModel)
            .where(
                ChatConversationModel.conversation_id == conversation_id,
                ChatConversationModel.tenant_id == tenant.tenant_id,
                ChatConversationModel.owner_user_id == tenant.user_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.scalar_one_or_none()
        return chat_conversation_to_record(model) if model is not None else None

    async def list_conversations(
        self,
        tenant: TenantContext,
        *,
        project_id: UUID | None = None,
        archived: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ChatConversationRecord], int]:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        clauses = [
            ChatConversationModel.tenant_id == tenant.tenant_id,
            ChatConversationModel.owner_user_id == tenant.user_id,
        ]
        if project_id is not None:
            clauses.append(ChatConversationModel.project_id == project_id)
        if archived is not None:
            clauses.append(ChatConversationModel.archived == archived)
        total_result = await self._session.execute(
            select(ChatConversationModel.conversation_id).where(*clauses)
        )
        total = len(list(total_result.scalars().all()))
        result = await self._session.execute(
            select(ChatConversationModel)
            .where(*clauses)
            .order_by(ChatConversationModel.updated_at.desc().nullslast())
            .offset(offset)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        models = list(result.scalars().all())
        return [chat_conversation_to_record(model) for model in models], total

    async def update_conversation(
        self,
        tenant: TenantContext,
        conversation: ChatConversationRecord,
    ) -> ChatConversationRecord:
        require_matching_tenant(tenant, conversation.tenant_id)
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(ChatConversationModel).where(
                ChatConversationModel.conversation_id == conversation.conversation_id,
                ChatConversationModel.tenant_id == tenant.tenant_id,
                ChatConversationModel.owner_user_id == tenant.user_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError(
                "Chat conversation not found",
                details={"conversation_id": str(conversation.conversation_id)},
            )
        model.project_id = conversation.project_id
        model.title = conversation.title
        model.mode = conversation.mode
        model.document_id = conversation.document_id
        model.pending_expand_question = conversation.pending_expand_question
        model.conversation_context = conversation.conversation_context
        model.pinned = conversation.pinned
        model.archived = conversation.archived
        await self._session.flush()
        return chat_conversation_to_record(model)

    async def delete_conversation(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
    ) -> None:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(ChatConversationModel).where(
                ChatConversationModel.conversation_id == conversation_id,
                ChatConversationModel.tenant_id == tenant.tenant_id,
                ChatConversationModel.owner_user_id == tenant.user_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        await self._session.delete(model)
        await self._session.flush()

    async def list_messages(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
    ) -> list[ChatMessageRecord]:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(ChatMessageModel)
            .where(
                ChatMessageModel.conversation_id == conversation_id,
                ChatMessageModel.tenant_id == tenant.tenant_id,
            )
            .order_by(ChatMessageModel.created_at.asc())
        )
        models = list(result.scalars().all())
        return [chat_message_to_record(model) for model in models]

    async def add_message(
        self,
        tenant: TenantContext,
        message: ChatMessageRecord,
    ) -> ChatMessageRecord:
        require_matching_tenant(tenant, message.tenant_id)
        await set_tenant_context(self._session, tenant)
        model = ChatMessageModel(
            message_id=message.message_id,
            tenant_id=message.tenant_id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            citations=list(message.citations),
            warnings=list(message.warnings),
            retrieval_mode=message.retrieval_mode,
            retrieval_trace_id=message.retrieval_trace_id,
            graph_paths=list(message.graph_paths),
        )
        self._session.add(model)
        await self._session.flush()
        return chat_message_to_record(model)
