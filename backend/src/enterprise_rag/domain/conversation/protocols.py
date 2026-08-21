"""Repository ports for chat projects and conversations."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from enterprise_rag.domain.conversation.records import (
    ChatConversationRecord,
    ChatMessageRecord,
    ChatProjectRecord,
)
from enterprise_rag.domain.tenant import TenantContext


class ChatProjectRepository(Protocol):
    """Chat project (folder) port."""

    async def create_project(
        self,
        tenant: TenantContext,
        project: ChatProjectRecord,
    ) -> ChatProjectRecord:
        """Insert a project for the authorized tenant/owner."""
        ...

    async def get_project(
        self,
        tenant: TenantContext,
        project_id: UUID,
    ) -> ChatProjectRecord | None:
        """Fetch a tenant/owner-scoped project."""
        ...

    async def list_projects(
        self,
        tenant: TenantContext,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[ChatProjectRecord], int]:
        """List tenant/owner-scoped projects (newest first when timestamps exist)."""
        ...

    async def update_project(
        self,
        tenant: TenantContext,
        project: ChatProjectRecord,
    ) -> ChatProjectRecord:
        """Update a tenant/owner-scoped project."""
        ...

    async def delete_project(
        self,
        tenant: TenantContext,
        project_id: UUID,
    ) -> None:
        """Delete a project; conversations referencing it are un-filed, not deleted."""
        ...


class ChatConversationRepository(Protocol):
    """Chat conversation + message port.

    Messages are not a top-level CRUD resource: they only exist as a side
    effect of asking a question via ``/query`` (``add_message``), and are
    only ever read as part of a conversation's history (``list_messages``).
    """

    async def create_conversation(
        self,
        tenant: TenantContext,
        conversation: ChatConversationRecord,
    ) -> ChatConversationRecord:
        """Insert a conversation for the authorized tenant/owner."""
        ...

    async def get_conversation(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
    ) -> ChatConversationRecord | None:
        """Fetch a tenant/owner-scoped conversation."""
        ...

    async def list_conversations(
        self,
        tenant: TenantContext,
        *,
        project_id: UUID | None = None,
        archived: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ChatConversationRecord], int]:
        """List tenant/owner-scoped conversations (newest first)."""
        ...

    async def update_conversation(
        self,
        tenant: TenantContext,
        conversation: ChatConversationRecord,
    ) -> ChatConversationRecord:
        """Update a tenant/owner-scoped conversation."""
        ...

    async def delete_conversation(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
    ) -> None:
        """Delete a conversation; its messages cascade with it."""
        ...

    async def list_messages(
        self,
        tenant: TenantContext,
        conversation_id: UUID,
    ) -> list[ChatMessageRecord]:
        """List a conversation's messages in chronological order."""
        ...

    async def add_message(
        self,
        tenant: TenantContext,
        message: ChatMessageRecord,
    ) -> ChatMessageRecord:
        """Append a message to a conversation."""
        ...
