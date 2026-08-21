"""ORM models for chat projects, conversations, and messages."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from enterprise_rag.domain.ids import new_id
from enterprise_rag.infrastructure.persistence.postgres.base import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
)


class ChatProjectModel(Base, TimestampMixin, TenantOwnedMixin):
    """Chat project (folder) a conversation can be filed under."""

    __tablename__ = "chat_projects"

    project_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ChatConversationModel(Base, TimestampMixin, TenantOwnedMixin):
    """Chat conversation (thread)."""

    __tablename__ = "chat_conversations"

    conversation_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chat_projects.project_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="New chat")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    document_id: Mapped[UUID | None] = mapped_column(nullable=True)
    pending_expand_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversation_context: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ChatMessageModel(Base, TimestampMixin, TenantOwnedMixin):
    """Message within a chat conversation."""

    __tablename__ = "chat_messages"
    __table_args__ = (CheckConstraint("role IN ('user', 'assistant')", name="role"),)

    message_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    warnings: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    retrieval_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retrieval_trace_id: Mapped[UUID | None] = mapped_column(nullable=True)
    graph_paths: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
