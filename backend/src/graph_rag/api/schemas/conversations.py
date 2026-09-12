"""Chat project/conversation/message API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.types import JsonValue


class ChatProjectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    name: str
    pinned: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChatProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None = None
    name: str = Field(min_length=1)


class ChatProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    pinned: bool | None = None


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    role: str
    content: str
    interaction_mode: Literal["chat", "search"] = "search"
    citations: list[dict[str, JsonValue]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retrieval_mode: str | None = None
    retrieval_trace_id: UUID | None = None
    graph_paths: list[dict[str, JsonValue]] = Field(default_factory=list)
    created_at: datetime | None = None


class ChatConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    project_id: UUID | None = None
    title: str
    mode: str
    interaction_mode: Literal["chat", "search"] = "chat"
    document_id: UUID | None = None
    pending_expand_question: str | None = None
    conversation_context: dict[str, JsonValue] | None = None
    pinned: bool = False
    archived: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChatConversationDetailResponse(ChatConversationResponse):
    messages: list[ChatMessageResponse] = Field(default_factory=list)


class ChatConversationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ChatConversationResponse]
    total: int
    offset: int
    limit: int


class ChatConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID | None = None
    title: str | None = None
    mode: str = "auto"
    interaction_mode: Literal["chat", "search"] = "chat"
    document_id: UUID | None = None
    project_id: UUID | None = None


class ChatConversationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    mode: str | None = None
    interaction_mode: Literal["chat", "search"] | None = None
    document_id: UUID | None = None
    project_id: UUID | None = None
    pinned: bool | None = None
    archived: bool | None = None
