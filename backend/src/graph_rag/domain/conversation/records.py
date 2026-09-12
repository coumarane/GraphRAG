"""Persistence-facing domain records for chat conversations, messages, and projects."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.types import JsonValue


class ChatProjectRecord(BaseModel):
    """Persisted chat project (folder) a conversation can belong to."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    tenant_id: UUID
    owner_user_id: UUID | None = None
    name: str
    pinned: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChatConversationRecord(BaseModel):
    """Persisted chat conversation (thread)."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    tenant_id: UUID
    owner_user_id: UUID | None = None
    project_id: UUID | None = None
    title: str = "New chat"
    mode: str = "auto"
    interaction_mode: Literal["chat", "search"] = "chat"
    document_id: UUID | None = None
    pending_expand_question: str | None = None
    conversation_context: dict[str, JsonValue] | None = None
    pinned: bool = False
    archived: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChatMessageRecord(BaseModel):
    """Persisted chat message within a conversation."""

    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    role: str
    content: str
    interaction_mode: Literal["chat", "search"] = "search"
    citations: list[dict[str, JsonValue]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retrieval_mode: str | None = None
    retrieval_trace_id: UUID | None = None
    graph_paths: list[dict[str, JsonValue]] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
