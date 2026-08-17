"""Transactional outbox, dead letters, and stage worker heartbeats.

Revision ID: 0006_ingestion_outbox
Revises: 0005_abac_quotas
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_ingestion_outbox"
down_revision: str | Sequence[str] | None = "0005_abac_quotas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingestion_runs", sa.Column("worker_id", sa.String(length=128), nullable=True))
    op.add_column(
        "ingestion_runs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ingestion_runs_worker_id", "ingestion_runs", ["worker_id"])
    op.create_index("ix_ingestion_runs_heartbeat_at", "ingestion_runs", ["heartbeat_at"])

    op.add_column("ingestion_stages", sa.Column("worker_id", sa.String(length=128), nullable=True))
    op.add_column(
        "ingestion_stages",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ingestion_stages_worker_id", "ingestion_stages", ["worker_id"])
    op.create_index("ix_ingestion_stages_heartbeat_at", "ingestion_stages", ["heartbeat_at"])

    op.create_table(
        "outbox_events",
        sa.Column("outbox_event_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stream_message_id", sa.String(length=64), nullable=True),
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
        sa.PrimaryKeyConstraint("outbox_event_id", name=op.f("pk_outbox_events")),
        sa.UniqueConstraint(
            "tenant_id",
            "event_type",
            "aggregate_id",
            name="uq_outbox_events_tenant_type_aggregate",
        ),
    )
    op.create_index("ix_outbox_events_tenant_id", "outbox_events", ["tenant_id"])
    op.create_index("ix_outbox_events_published_at", "outbox_events", ["published_at"])
    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["created_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )

    op.create_table(
        "ingestion_dead_letters",
        sa.Column("dead_letter_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=128), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("original_stream_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name=op.f("fk_ingestion_dead_letters_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("dead_letter_id", name=op.f("pk_ingestion_dead_letters")),
    )
    op.create_index(
        "ix_ingestion_dead_letters_tenant_id",
        "ingestion_dead_letters",
        ["tenant_id"],
    )
    op.create_index(
        "ix_ingestion_dead_letters_ingestion_run_id",
        "ingestion_dead_letters",
        ["ingestion_run_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("ALTER TABLE ingestion_dead_letters ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text("ALTER TABLE ingestion_dead_letters FORCE ROW LEVEL SECURITY"))
        op.execute(
            sa.text(
                """
                CREATE POLICY tenant_isolation ON ingestion_dead_letters
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
        op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON ingestion_dead_letters"))
        op.execute(sa.text("ALTER TABLE ingestion_dead_letters DISABLE ROW LEVEL SECURITY"))
    op.drop_table("ingestion_dead_letters")
    op.drop_index("ix_outbox_events_unpublished", table_name="outbox_events")
    op.drop_index("ix_outbox_events_published_at", table_name="outbox_events")
    op.drop_index("ix_outbox_events_tenant_id", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_ingestion_stages_heartbeat_at", table_name="ingestion_stages")
    op.drop_index("ix_ingestion_stages_worker_id", table_name="ingestion_stages")
    op.drop_column("ingestion_stages", "heartbeat_at")
    op.drop_column("ingestion_stages", "worker_id")
    op.drop_index("ix_ingestion_runs_heartbeat_at", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_worker_id", table_name="ingestion_runs")
    op.drop_column("ingestion_runs", "heartbeat_at")
    op.drop_column("ingestion_runs", "worker_id")
