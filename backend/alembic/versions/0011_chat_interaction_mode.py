"""Add interaction_mode (chat vs search) to chat conversations and messages.

Revision ID: 0011_chat_interaction_mode
Revises: 0010_di_promote_to_metadata
Create Date: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_chat_interaction_mode"
down_revision: str | Sequence[str] | None = "0010_di_promote_to_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_conversations",
        sa.Column(
            "interaction_mode",
            sa.String(length=16),
            nullable=False,
            server_default="chat",
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "interaction_mode",
            sa.String(length=16),
            nullable=False,
            # Every message persisted before this migration came from the
            # grounded-search flow (plain chat did not exist yet).
            server_default="search",
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "interaction_mode")
    op.drop_column("chat_conversations", "interaction_mode")
