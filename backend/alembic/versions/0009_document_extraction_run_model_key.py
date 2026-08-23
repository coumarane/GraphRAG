"""Add model_key to document_extraction_runs.

document_extraction_runs.model_id is a FK to persisted custom models only;
runs against a built-in model (no database row) had nowhere to record which
one was used.

Revision ID: 0009_document_extraction_run_model_key
Revises: 0008_document_intelligence
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_document_extraction_run_model_key"
down_revision: str | Sequence[str] | None = "0008_document_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_extraction_runs",
        sa.Column("model_key", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_document_extraction_runs_model_key",
        "document_extraction_runs",
        ["model_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_extraction_runs_model_key", table_name="document_extraction_runs")
    op.drop_column("document_extraction_runs", "model_key")
