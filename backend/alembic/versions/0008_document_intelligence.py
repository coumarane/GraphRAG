"""Document Intelligence plugin: plugin registry + structured extraction tables.

Revision ID: 0008_document_intelligence
Revises: 0007_conversations
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_document_intelligence"
down_revision: str | Sequence[str] | None = "0007_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plugins",
        sa.Column("plugin_id", sa.Uuid(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("plugin_name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="0.0.0"),
        sa.Column("trust_tier", sa.String(length=16), nullable=False, server_default="community"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
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
        sa.PrimaryKeyConstraint("plugin_id", name="pk_plugins"),
        sa.UniqueConstraint("capability", "plugin_name", name="uq_plugins_capability_plugin_name"),
    )
    op.create_index("ix_plugins_capability", "plugins", ["capability"], unique=False)

    op.create_table(
        "plugin_configuration",
        sa.Column("config_id", sa.Uuid(), nullable=False),
        sa.Column("plugin_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
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
            ["plugin_id"],
            ["plugins.plugin_id"],
            name="fk_plugin_configuration_plugin_id_plugins",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("config_id", name="pk_plugin_configuration"),
        sa.UniqueConstraint("plugin_id", "tenant_id", name="uq_plugin_configuration_plugin_tenant"),
    )
    op.create_index(
        "ix_plugin_configuration_plugin_id", "plugin_configuration", ["plugin_id"], unique=False
    )
    op.create_index(
        "ix_plugin_configuration_tenant_id", "plugin_configuration", ["tenant_id"], unique=False
    )

    op.create_table(
        "document_intelligence_models",
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("model_type", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="1.0"),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="internal"),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
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
            name="fk_document_intelligence_models_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("model_id", name="pk_document_intelligence_models"),
        sa.UniqueConstraint(
            "tenant_id",
            "model_key",
            "version",
            name="uq_document_intelligence_models_tenant_key_version",
        ),
    )
    op.create_index(
        "ix_document_intelligence_models_tenant_id",
        "document_intelligence_models",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_intelligence_models_model_key",
        "document_intelligence_models",
        ["model_key"],
        unique=False,
    )

    op.create_table(
        "document_intelligence_model_fields",
        sa.Column("field_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("field_type", sa.String(length=32), nullable=False),
        sa.Column(
            "default_selected", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
            name="fk_document_intelligence_model_fields_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["document_intelligence_models.model_id"],
            name="fk_document_intelligence_model_fields_model_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("field_id", name="pk_document_intelligence_model_fields"),
    )
    op.create_index(
        "ix_document_intelligence_model_fields_model_id",
        "document_intelligence_model_fields",
        ["model_id"],
        unique=False,
    )

    op.create_table(
        "document_extraction_runs",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=True),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="internal"),
        sa.Column("plugin_version", sa.String(length=32), nullable=False, server_default="0.0.0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("fingerprint", sa.String(length=128), nullable=True),
        sa.Column("selected_fields_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            name="fk_document_extraction_runs_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name="fk_document_extraction_runs_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            name="fk_document_extraction_runs_version_id_document_versions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name="fk_document_extraction_runs_ingestion_run_id_ingestion_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["document_intelligence_models.model_id"],
            name="fk_document_extraction_runs_model_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_document_extraction_runs"),
    )
    op.create_index(
        "ix_document_extraction_runs_tenant_id",
        "document_extraction_runs",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_extraction_runs_document_id",
        "document_extraction_runs",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_extraction_runs_version_id",
        "document_extraction_runs",
        ["version_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_extraction_runs_ingestion_run_id",
        "document_extraction_runs",
        ["ingestion_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_extraction_runs_fingerprint",
        "document_extraction_runs",
        ["fingerprint"],
        unique=False,
    )

    op.create_table(
        "document_extracted_fields",
        sa.Column("extracted_field_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("normalized_value_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence_band", sa.String(length=8), nullable=False, server_default="LOW"),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("bounding_box_json", sa.JSON(), nullable=True),
        sa.Column("extraction_method", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
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
            name="fk_document_extracted_fields_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["document_extraction_runs.run_id"],
            name="fk_document_extracted_fields_run_id_document_extraction_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("extracted_field_id", name="pk_document_extracted_fields"),
        sa.UniqueConstraint("run_id", "name", name="uq_document_extracted_fields_run_name"),
    )
    op.create_index(
        "ix_document_extracted_fields_tenant_id",
        "document_extracted_fields",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_extracted_fields_run_id",
        "document_extracted_fields",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_extracted_fields_name",
        "document_extracted_fields",
        ["name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_extracted_fields_name", table_name="document_extracted_fields")
    op.drop_index("ix_document_extracted_fields_run_id", table_name="document_extracted_fields")
    op.drop_index("ix_document_extracted_fields_tenant_id", table_name="document_extracted_fields")
    op.drop_table("document_extracted_fields")

    op.drop_index("ix_document_extraction_runs_fingerprint", table_name="document_extraction_runs")
    op.drop_index(
        "ix_document_extraction_runs_ingestion_run_id", table_name="document_extraction_runs"
    )
    op.drop_index("ix_document_extraction_runs_version_id", table_name="document_extraction_runs")
    op.drop_index("ix_document_extraction_runs_document_id", table_name="document_extraction_runs")
    op.drop_index("ix_document_extraction_runs_tenant_id", table_name="document_extraction_runs")
    op.drop_table("document_extraction_runs")

    op.drop_index(
        "ix_document_intelligence_model_fields_model_id",
        table_name="document_intelligence_model_fields",
    )
    op.drop_table("document_intelligence_model_fields")

    op.drop_index(
        "ix_document_intelligence_models_model_key", table_name="document_intelligence_models"
    )
    op.drop_index(
        "ix_document_intelligence_models_tenant_id", table_name="document_intelligence_models"
    )
    op.drop_table("document_intelligence_models")

    op.drop_index("ix_plugin_configuration_tenant_id", table_name="plugin_configuration")
    op.drop_index("ix_plugin_configuration_plugin_id", table_name="plugin_configuration")
    op.drop_table("plugin_configuration")

    op.drop_index("ix_plugins_capability", table_name="plugins")
    op.drop_table("plugins")
