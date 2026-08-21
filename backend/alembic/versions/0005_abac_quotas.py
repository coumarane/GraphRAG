"""ABAC authorization policies, tenant memberships, and quota tables.

Revision ID: 0005_abac_quotas
Revises: 0004_model_usage
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_abac_quotas"
down_revision: str | Sequence[str] | None = "0004_model_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
    )
    op.add_column(
        "users",
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # Migrate legacy role/is_active into status + attributes.admin
    op.execute(
        """
        UPDATE users
        SET status = CASE WHEN is_active THEN 'active' ELSE 'disabled' END,
            attributes = CASE
                WHEN role = 'admin' THEN jsonb_set(COALESCE(attributes, '{}'::jsonb), '{admin}', 'true'::jsonb, true)
                ELSE COALESCE(attributes, '{}'::jsonb)
            END
        """
    )

    op.add_column("documents", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("department", sa.String(length=128), nullable=True))
    op.add_column("documents", sa.Column("country", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("business_unit", sa.String(length=128), nullable=True))
    op.add_column("documents", sa.Column("classification", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("required_clearance", sa.Integer(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "allowed_groups",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_foreign_key(
        "fk_documents_owner_user_id",
        "documents",
        "users",
        ["owner_user_id"],
        ["user_id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "tenant_memberships",
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "attributes",
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("membership_id"),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_tenant_memberships_user_tenant"),
    )
    op.create_index("ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"])
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"])

    # Backfill memberships from primary tenant on users
    op.execute(
        """
        INSERT INTO tenant_memberships (membership_id, user_id, tenant_id, status, attributes)
        SELECT md5(random()::text || clock_timestamp()::text)::uuid, user_id, tenant_id, status, attributes
        FROM users
        ON CONFLICT DO NOTHING
        """
    )

    op.create_table(
        "authorization_policies",
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("effect", sa.String(length=16), nullable=False, server_default="allow"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column(
            "document",
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("policy_id"),
    )
    op.create_index("ix_authorization_policies_tenant_id", "authorization_policies", ["tenant_id"])
    op.create_index("ix_authorization_policies_action", "authorization_policies", ["action"])

    op.create_table(
        "policy_versions",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "document",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["policy_id"], ["authorization_policies.policy_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint("policy_id", "version_number", name="uq_policy_versions_number"),
    )

    op.create_table(
        "quota_plans",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "limits",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metadata",
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
        sa.PrimaryKeyConstraint("plan_id"),
        sa.UniqueConstraint("name", name="uq_quota_plans_name"),
    )

    op.create_table(
        "quota_assignments",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(length=32), nullable=False, server_default="month"),
        sa.Column(
            "overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["quota_plans.plan_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("assignment_id"),
    )
    op.create_index("ix_quota_assignments_tenant_id", "quota_assignments", ["tenant_id"])
    op.create_index("ix_quota_assignments_user_id", "quota_assignments", ["user_id"])

    op.create_table(
        "usage_counters",
        sa.Column("counter_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("period", sa.String(length=32), nullable=False),
        sa.Column("period_key", sa.String(length=32), nullable=False),
        sa.Column("used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("counter_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "metric",
            "period",
            "period_key",
            name="uq_usage_counters_scope",
        ),
    )
    op.create_index("ix_usage_counters_tenant_id", "usage_counters", ["tenant_id"])

    op.create_table(
        "quota_reservations",
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("period", sa.String(length=32), nullable=False),
        sa.Column("period_key", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="reserved"),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("reservation_id"),
    )

    op.create_table(
        "quota_usage_events",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("usage_type", sa.String(length=64), nullable=False, server_default="actual"),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("query_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "metadata",
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["quota_reservations.reservation_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_quota_usage_events_tenant_id", "quota_usage_events", ["tenant_id"])
    op.create_index("ix_quota_usage_events_user_id", "quota_usage_events", ["user_id"])

    op.add_column("model_usage_events", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_model_usage_events_user_id",
        "model_usage_events",
        "users",
        ["user_id"],
        ["user_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_model_usage_events_user_id", "model_usage_events", type_="foreignkey")
    op.drop_column("model_usage_events", "user_id")
    op.drop_table("quota_usage_events")
    op.drop_table("quota_reservations")
    op.drop_table("usage_counters")
    op.drop_table("quota_assignments")
    op.drop_table("quota_plans")
    op.drop_table("policy_versions")
    op.drop_table("authorization_policies")
    op.drop_table("tenant_memberships")
    op.drop_constraint("fk_documents_owner_user_id", "documents", type_="foreignkey")
    op.drop_column("documents", "allowed_groups")
    op.drop_column("documents", "required_clearance")
    op.drop_column("documents", "classification")
    op.drop_column("documents", "business_unit")
    op.drop_column("documents", "country")
    op.drop_column("documents", "department")
    op.drop_column("documents", "owner_user_id")
    op.drop_column("users", "attributes")
    op.drop_column("users", "status")
