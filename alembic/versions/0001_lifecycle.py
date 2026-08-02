"""Initial lifecycle schema with tenant RLS scaffolding.

Revision ID: 0001_lifecycle
Revises:
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_lifecycle"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_OWNED_TABLES = (
    "documents",
    "document_versions",
    "ingestion_runs",
    "ingestion_stages",
    "parser_attempts",
)


def _json_type() -> sa.types.TypeEngine[object]:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata", _json_type(), nullable=False),
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
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("tenant_key", name=op.f("uq_tenants_tenant_key")),
    )

    op.create_table(
        "documents",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("document_type", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("tags", _json_type(), nullable=False),
        sa.Column("security_labels", _json_type(), nullable=False),
        sa.Column("metadata", _json_type(), nullable=False),
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
        sa.PrimaryKeyConstraint("document_id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_tenant_id"), "documents", ["tenant_id"], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_filename", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("original_object_key", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("metadata", _json_type(), nullable=False),
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
            ["document_id"],
            ["documents.document_id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("version_id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "version_number",
            name="uq_document_versions_number",
        ),
    )
    op.create_index(
        op.f("ix_document_versions_tenant_id"),
        "document_versions",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_versions_document_id"),
        "document_versions",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_versions_content_hash"),
        "document_versions",
        ["content_hash"],
        unique=False,
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("parser_requested", sa.String(length=128), nullable=True),
        sa.Column("parser_used", sa.String(length=128), nullable=True),
        sa.Column("config_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("pages_processed", sa.Integer(), nullable=False),
        sa.Column("elements_processed", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("latest_warning", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("metadata", _json_type(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["document_id"],
            ["documents.document_id"],
            name=op.f("fk_ingestion_runs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            name=op.f("fk_ingestion_runs_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ingestion_run_id", name=op.f("pk_ingestion_runs")),
    )
    op.create_index(
        op.f("ix_ingestion_runs_tenant_id"),
        "ingestion_runs",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_runs_document_id"),
        "ingestion_runs",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_runs_version_id"),
        "ingestion_runs",
        ["version_id"],
        unique=False,
    )

    op.create_table(
        "ingestion_stages",
        sa.Column("stage_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("config_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", _json_type(), nullable=False),
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
            name=op.f("fk_ingestion_stages_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("stage_id", name=op.f("pk_ingestion_stages")),
        sa.UniqueConstraint(
            "tenant_id",
            "ingestion_run_id",
            "stage",
            name="uq_ingestion_stages_run_stage",
        ),
    )
    op.create_index(
        op.f("ix_ingestion_stages_tenant_id"),
        "ingestion_stages",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_stages_ingestion_run_id"),
        "ingestion_stages",
        ["ingestion_run_id"],
        unique=False,
    )

    op.create_table(
        "parser_attempts",
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("parser_name", sa.String(length=128), nullable=False),
        sa.Column("parser_version", sa.String(length=128), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("failure_category", sa.String(length=128), nullable=True),
        sa.Column("warnings", _json_type(), nullable=False),
        sa.Column("metadata", _json_type(), nullable=False),
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
            name=op.f("fk_parser_attempts_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("pk_parser_attempts")),
    )
    op.create_index(
        op.f("ix_parser_attempts_tenant_id"),
        "parser_attempts",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_parser_attempts_ingestion_run_id"),
        "parser_attempts",
        ["ingestion_run_id"],
        unique=False,
    )

    # RLS scaffolding (PostgreSQL only). Application sets app.tenant_id per transaction.
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

    op.drop_table("parser_attempts")
    op.drop_table("ingestion_stages")
    op.drop_table("ingestion_runs")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("tenants")
