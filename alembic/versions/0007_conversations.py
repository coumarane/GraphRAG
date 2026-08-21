"""Chat projects, conversations, and messages for server-side chat history.

Revision ID: 0007_conversations
Revises: 0006_ingestion_outbox
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_conversations"
down_revision: str | Sequence[str] | None = "0006_ingestion_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_OWNED_TABLES = (
    "chat_projects",
    "chat_conversations",
    "chat_messages",
)


def _json_type() -> sa.types.TypeEngine[object]:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    created_at, updated_at = _timestamps()
    op.create_table(
        "chat_projects",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.user_id"],
            name=op.f("fk_chat_projects_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_chat_projects")),
    )
    op.create_index(op.f("ix_chat_projects_tenant_id"), "chat_projects", ["tenant_id"])
    op.create_index(op.f("ix_chat_projects_owner_user_id"), "chat_projects", ["owner_user_id"])
    op.create_index(
        "ix_chat_projects_tenant_owner", "chat_projects", ["tenant_id", "owner_user_id"]
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "chat_conversations",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("pending_expand_question", sa.Text(), nullable=True),
        sa.Column("conversation_context", _json_type(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.user_id"],
            name=op.f("fk_chat_conversations_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["chat_projects.project_id"],
            name=op.f("fk_chat_conversations_project_id_chat_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("conversation_id", name=op.f("pk_chat_conversations")),
    )
    op.create_index(op.f("ix_chat_conversations_tenant_id"), "chat_conversations", ["tenant_id"])
    op.create_index(
        op.f("ix_chat_conversations_owner_user_id"), "chat_conversations", ["owner_user_id"]
    )
    op.create_index(
        op.f("ix_chat_conversations_project_id"), "chat_conversations", ["project_id"]
    )
    op.create_index(
        "ix_chat_conversations_tenant_owner_updated",
        "chat_conversations",
        ["tenant_id", "owner_user_id", "updated_at"],
    )
    op.create_index(
        "ix_chat_conversations_tenant_project",
        "chat_conversations",
        ["tenant_id", "project_id"],
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "chat_messages",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", _json_type(), nullable=False),
        sa.Column("warnings", _json_type(), nullable=False),
        sa.Column("retrieval_mode", sa.String(length=32), nullable=True),
        sa.Column("retrieval_trace_id", sa.Uuid(), nullable=True),
        sa.Column("graph_paths", _json_type(), nullable=False),
        created_at,
        updated_at,
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_chat_messages_role")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["chat_conversations.conversation_id"],
            name=op.f("fk_chat_messages_conversation_id_chat_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_chat_messages")),
    )
    op.create_index(op.f("ix_chat_messages_tenant_id"), "chat_messages", ["tenant_id"])
    op.create_index(
        op.f("ix_chat_messages_conversation_id"), "chat_messages", ["conversation_id"]
    )
    op.create_index(
        "ix_chat_messages_conversation_created",
        "chat_messages",
        ["conversation_id", "created_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in TENANT_OWNED_TABLES:
            op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            op.execute(
                sa.text(
                    f"""
                    CREATE POLICY tenant_isolation ON {table}
                    FOR ALL
                    USING (
                        tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
                    )
                    WITH CHECK (
                        tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
                    )
                    """
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in reversed(TENANT_OWNED_TABLES):
            op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
            op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")
    op.drop_table("chat_projects")
