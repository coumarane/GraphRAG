"""Add promote_to_document_metadata to document_intelligence_model_fields.

Revision ID: 0010_di_promote_to_metadata
Revises: 0009_extraction_run_model_key
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_di_promote_to_metadata"
down_revision: str | Sequence[str] | None = "0009_extraction_run_model_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_intelligence_model_fields",
        sa.Column(
            "promote_to_document_metadata",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("document_intelligence_model_fields", "promote_to_document_metadata")
