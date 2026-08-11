"""Model usage events ledger for OpenAI-style cost metering.

Revision ID: 0004_model_usage
Revises: 0003_auth_users
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_model_usage"
down_revision: str | Sequence[str] | None = "0003_auth_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_usage_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_usd", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("known_pricing", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=True),
        sa.Column("query_id", sa.Uuid(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name="fk_model_usage_events_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_model_usage_events"),
    )
    op.create_index(
        "ix_model_usage_events_tenant_id_created_at",
        "model_usage_events",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_model_usage_events_tenant_id_capability_created_at",
        "model_usage_events",
        ["tenant_id", "capability", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_model_usage_events_tenant_id_model_name_created_at",
        "model_usage_events",
        ["tenant_id", "model_name", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_usage_events_tenant_id_model_name_created_at",
        table_name="model_usage_events",
    )
    op.drop_index(
        "ix_model_usage_events_tenant_id_capability_created_at",
        table_name="model_usage_events",
    )
    op.drop_index(
        "ix_model_usage_events_tenant_id_created_at",
        table_name="model_usage_events",
    )
    op.drop_table("model_usage_events")
