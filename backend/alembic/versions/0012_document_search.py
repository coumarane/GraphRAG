"""Document/field search: fix JSON->JSONB drift, add full-text + lookup indexes.

``document_extracted_fields.value_json``/``normalized_value_json`` were
declared as plain ``JSON`` in migration 0008, but the current ORM model
(``infrastructure.persistence.postgres.models.document_intelligence``)
declares them as ``JSON().with_variant(JSONB(), "postgresql")`` -- this
migration brings the actual Postgres column type in line with what the
model has always assumed, and adds the indexes the new document/field
search repository (``SqlAlchemyDocumentSearchRepository``) depends on.

Revision ID: 0012_document_search
Revises: 0011_chat_interaction_mode
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_document_search"
down_revision: str | Sequence[str] | None = "0011_chat_interaction_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "document_extracted_fields",
        "value_json",
        type_=postgresql.JSONB(),
        postgresql_using="value_json::jsonb",
    )
    op.alter_column(
        "document_extracted_fields",
        "normalized_value_json",
        type_=postgresql.JSONB(),
        postgresql_using="normalized_value_json::jsonb",
    )

    # Composite index for the per-field-filter EXISTS/JOIN lookup used by
    # document search -- today only a single-column index on `name` exists.
    op.create_index(
        "ix_document_extracted_fields_tenant_id_name",
        "document_extracted_fields",
        ["tenant_id", "name"],
        unique=False,
    )

    # Expression GIN index for free-text title search. Must stay textually
    # identical to the `to_tsvector('simple', documents.title)` expression
    # in SqlAlchemyDocumentSearchRepository.search() for Postgres to use it.
    op.execute(
        "CREATE INDEX ix_documents_title_fts ON documents "
        "USING GIN (to_tsvector('simple', title))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_title_fts")
    op.drop_index(
        "ix_document_extracted_fields_tenant_id_name", table_name="document_extracted_fields"
    )
    op.alter_column(
        "document_extracted_fields",
        "normalized_value_json",
        type_=sa.JSON(),
        postgresql_using="normalized_value_json::json",
    )
    op.alter_column(
        "document_extracted_fields",
        "value_json",
        type_=sa.JSON(),
        postgresql_using="value_json::json",
    )
