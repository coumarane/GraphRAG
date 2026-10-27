"""Upload sessions and pinned original identity.

Revision ID: 0013_upload_sessions
Revises: 0012_document_search
Create Date: 2026-10-27

Additive. Existing document and run rows are not rewritten. Downgrade drops
only this table and the two nullable version columns added here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_upload_sessions"
down_revision: str | Sequence[str] | None = "0012_document_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_versions", sa.Column("etag", sa.String(length=256), nullable=True))
    op.add_column(
        "document_versions",
        sa.Column("object_version_id", sa.String(length=256), nullable=True),
    )
    op.create_table(
        "upload_sessions",
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("staging_object_key", sa.Text(), nullable=True),
        sa.Column("final_object_key", sa.Text(), nullable=True),
        sa.Column("source_filename", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("declared_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("actual_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("etag", sa.String(length=256), nullable=True),
        sa.Column("object_version_id", sa.String(length=256), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("document_reservation_id", sa.Uuid(), nullable=True),
        sa.Column("storage_reservation_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
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
        sa.PrimaryKeyConstraint("upload_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "staging_object_key",
            name="uq_upload_sessions_staging_key",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "final_object_key",
            name="uq_upload_sessions_final_key",
        ),
        sa.UniqueConstraint("ingestion_run_id", name="uq_upload_sessions_run"),
    )
    op.create_index(
        "ix_upload_sessions_tenant_status_expires",
        "upload_sessions",
        ["tenant_id", "status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_upload_sessions_tenant_status_expires", table_name="upload_sessions")
    op.drop_table("upload_sessions")
    op.drop_column("document_versions", "object_version_id")
    op.drop_column("document_versions", "etag")
