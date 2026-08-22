"""In-memory chat project/conversation repositories for local mode and tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from graph_rag.domain.conversation.records import (
    ChatConversationRecord,
    ChatMessageRecord,
    ChatProjectRecord,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import AuthorizationError, ConflictError, NotFoundError


def _stamped(record: ChatProjectRecord | ChatConversationRecord | ChatMessageRecord):
    """Mirror Postgres's server_default=func.now() so in-memory ordering matches."""
    if record.created_at is not None and record.updated_at is not None:
        return record
    now = datetime.now(UTC)
    return record.model_copy(
        update={
            "created_at": record.created_at or now,
            "updated_at": record.updated_at or now,
        }
    )


class InMemoryChatProjectRepository:
    """Chat project store for local mode.

    Unlike the Postgres repo, there's no real FK here to un-file conversations
    for free when their project is deleted (ON DELETE SET NULL) — this store
    has to replicate that explicitly against the paired conversation store.
    """

    def __init__(self, conversations: InMemoryChatConversationRepository | None = None) -> None:
        self.projects: dict[tuple[UUID, UUID], ChatProjectRecord] = {}
        self._conversations = conversations

    @staticmethod
    def _assert_tenant(tenant: TenantContext, owner: UUID) -> None:
        if tenant.tenant_id != owner:
            raise AuthorizationError("Chat project tenant mismatch")

    @staticmethod
    def _owned(tenant: TenantContext, project: ChatProjectRecord) -> bool:
        return project.owner_user_id == tenant.user_id

    async def create_project(
        self,
        tenant: TenantContext,
        project: ChatProjectRecord,
    ) -> ChatProjectRecord:
        self._assert_tenant(tenant, project.tenant_id)
        key = (tenant.tenant_id, project.project_id)
        if key in self.projects:
            raise ConflictError("Chat project already exists")
        record = _stamped(project.model_copy(update={"owner_user_id": tenant.user_id}))
        self.projects[key] = record
        return record

    async def get_project(
        self,
        tenant: TenantContext,
        project_id: UUID,
    ) -> ChatProjectRecord | None:
        project = self.projects.get((tenant.tenant_id, project_id))
        if project is None or not self._owned(tenant, project):
            return None
        return project

    async def list_projects(
        self,
        tenant: TenantContext,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[ChatProjectRecord], int]:
        items = [
            project
            for (owner, _project_id), project in self.projects.items()
            if owner == tenant.tenant_id and self._owned(tenant, project)
        ]
        items.sort(
            key=lambda item: item.updated_at or item.created_at or item.project_id.hex,
            reverse=True,
        )
        total = len(items)
        return items[offset : offset + limit], total

    async def update_project(
        self,
        tenant: TenantContext,
        project: ChatProjectRecord,
    ) -> ChatProjectRecord:
        self._assert_tenant(tenant, project.tenant_id)
        key = (tenant.tenant_id, project.project_id)
        existing = self.projects.get(key)
        if existing is None or not self._owned(tenant, existing):
            raise NotFoundError("Chat project not found")
        record = _stamped(
            project.model_copy(
                update={
                    "owner_user_id": tenant.user_id,
                    "created_at": existing.created_at,
                    "updated_at": datetime.now(UTC),
                }
            )
        )
        self.projects[key] = record
        return record

    async def delete_project(
        self,
        tenant: TenantContext,
        project_id: UUID,
    ) -> None:
        key = (tenant.tenant_id, project_id)
        existing = self.projects.get(key)
        if existing is None or not self._owned(tenant, existing):
            return
        del self.projects[key]
        if self._conversations is None:
            return
        for conv_key, conversation in list(self._conversations.conversations.items()):
            if conversation.tenant_id == tenant.tenant_id and conversation.project_id == project_id:
                self._conversations.conversations[conv_key] = conversation.model_copy(
                    update={"project_id": None, "updated_at": datetime.now(UTC)}
                )


class InMemoryChatConversationRepository:
    """Chat conversation/message store for local mode."""

    def __init__(self) -> None:
        self.conversations: dict[tuple[UUID, UUID], ChatConversationRecord] = {}
        self.messages: dict[tuple[UUID, UUID], list[ChatMessageRecord]] = {}

    @staticmethod
    def _assert_tenant(tenant: TenantContext, owner: UUID) -> None:
        if tenant.tenant_id != owner:
            raise AuthorizationError("Chat conversation tenant mismatch")

    @staticmethod
    def _owned(tenant: TenantContext, conversation: ChatConversationRecord) -> bool:
        return conversation.owner_user_id == tenant.user_id

    async def create_conversation(
        self,
        tenant: TenantContext,
        conversation: ChatConversationRecord,
    ) -> ChatConversationRecord:
        self._assert_tenant(tenant, conversation.tenant_id)
        key = (tenant.tenant_id, conversation.conversation_id)
        if key in self.conversations:
            raise ConflictError("Chat conversation already exists")
        record = _stamped(conversation.model_copy(update={"owner_user_id": tenant.user_id}))
        self.conversations[key] = record
        return record

    async def get_conversation(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
    ) -> ChatConversationRecord | None:
        conversation = self.conversations.get((tenant.tenant_id, conversation_id))
        if conversation is None or not self._owned(tenant, conversation):
            return None
        return conversation

    async def list_conversations(
        self,
        tenant: TenantContext,
        *,
        project_id: UUID | None = None,
        archived: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ChatConversationRecord], int]:
        items = [
            conversation
            for (owner, _conversation_id), conversation in self.conversations.items()
            if owner == tenant.tenant_id and self._owned(tenant, conversation)
        ]
        if project_id is not None:
            items = [item for item in items if item.project_id == project_id]
        if archived is not None:
            items = [item for item in items if item.archived == archived]
        items.sort(
            key=lambda item: item.updated_at or item.created_at or item.conversation_id.hex,
            reverse=True,
        )
        total = len(items)
        return items[offset : offset + limit], total

    async def update_conversation(
        self,
        tenant: TenantContext,
        conversation: ChatConversationRecord,
    ) -> ChatConversationRecord:
        self._assert_tenant(tenant, conversation.tenant_id)
        key = (tenant.tenant_id, conversation.conversation_id)
        existing = self.conversations.get(key)
        if existing is None or not self._owned(tenant, existing):
            raise NotFoundError("Chat conversation not found")
        record = _stamped(
            conversation.model_copy(
                update={
                    "owner_user_id": tenant.user_id,
                    "created_at": existing.created_at,
                    "updated_at": datetime.now(UTC),
                }
            )
        )
        self.conversations[key] = record
        return record

    async def delete_conversation(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
    ) -> None:
        key = (tenant.tenant_id, conversation_id)
        existing = self.conversations.get(key)
        if existing is None or not self._owned(tenant, existing):
            return
        del self.conversations[key]
        self.messages.pop(key, None)

    async def list_messages(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
    ) -> list[ChatMessageRecord]:
        return list(self.messages.get((tenant.tenant_id, conversation_id), []))

    async def add_message(
        self,
        tenant: TenantContext,
        message: ChatMessageRecord,
    ) -> ChatMessageRecord:
        self._assert_tenant(tenant, message.tenant_id)
        record = _stamped(message)
        key = (tenant.tenant_id, message.conversation_id)
        self.messages.setdefault(key, []).append(record)
        return record
