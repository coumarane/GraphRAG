"""Parsing audit schema for immutable document/page/element reports.

Revision ID: 0002_parsing_audit
Revises: 0001_lifecycle
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_parsing_audit"
down_revision: str | Sequence[str] | None = "0001_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_OWNED_TABLES = (
    "document_parse_reports",
    "page_parse_reports",
    "element_parse_reports",
    "processing_stage_runs",
    "parser_routing_decisions",
    "ingestion_parse_issues",
    "content_loss_records",
)


def _json_type() -> sa.types.TypeEngine[object]:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    created_at, updated_at = _timestamps()
    op.create_table(
        "document_parse_reports",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("total_pages", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("ingestion_status", sa.String(length=64), nullable=True),
        sa.Column("primary_parser", sa.String(length=128), nullable=True),
        sa.Column("parser_version", sa.String(length=128), nullable=True),
        sa.Column("fallback_parsers", _json_type(), nullable=False),
        sa.Column("ocr_strategy", sa.String(length=128), nullable=True),
        sa.Column("vision_strategy", sa.String(length=128), nullable=True),
        sa.Column("text_llm", sa.String(length=255), nullable=True),
        sa.Column("vision_llm", sa.String(length=255), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("config_profile", sa.String(length=128), nullable=True),
        sa.Column("app_version", sa.String(length=64), nullable=True),
        sa.Column("git_commit", sa.String(length=64), nullable=True),
        sa.Column("extraction_quality_score", sa.Float(), nullable=True),
        sa.Column("extraction_completeness", sa.Float(), nullable=True),
        sa.Column("ocr_coverage", sa.Float(), nullable=True),
        sa.Column("element_processing_coverage", sa.Float(), nullable=True),
        sa.Column("normalization_completeness", sa.Float(), nullable=True),
        sa.Column("total_detected_elements", sa.Integer(), nullable=False),
        sa.Column("total_processed_elements", sa.Integer(), nullable=False),
        sa.Column("total_failed_elements", sa.Integer(), nullable=False),
        sa.Column("total_skipped_elements", sa.Integer(), nullable=False),
        sa.Column("total_normalized_elements", sa.Integer(), nullable=False),
        sa.Column("total_warnings", sa.Integer(), nullable=False),
        sa.Column("total_errors", sa.Integer(), nullable=False),
        sa.Column("metadata", _json_type(), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            name=op.f("fk_document_parse_reports_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.version_id"],
            name=op.f("fk_document_parse_reports_version_id_document_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name=op.f("fk_document_parse_reports_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("report_id", name=op.f("pk_document_parse_reports")),
        sa.UniqueConstraint(
            "tenant_id",
            "ingestion_run_id",
            name="uq_document_parse_reports_tenant_run",
        ),
    )
    op.create_index(op.f("ix_document_parse_reports_tenant_id"), "document_parse_reports", ["tenant_id"])
    op.create_index(op.f("ix_document_parse_reports_document_id"), "document_parse_reports", ["document_id"])
    op.create_index(op.f("ix_document_parse_reports_version_id"), "document_parse_reports", ["version_id"])
    op.create_index(
        op.f("ix_document_parse_reports_ingestion_run_id"),
        "document_parse_reports",
        ["ingestion_run_id"],
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "page_parse_reports",
        sa.Column("page_report_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("page_width", sa.Float(), nullable=True),
        sa.Column("page_height", sa.Float(), nullable=True),
        sa.Column("has_native_text", sa.Boolean(), nullable=True),
        sa.Column("ocr_required", sa.Boolean(), nullable=True),
        sa.Column("ocr_engine", sa.String(length=128), nullable=True),
        sa.Column("page_parser", sa.String(length=128), nullable=True),
        sa.Column("fallback_parser", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("detected_elements", sa.Integer(), nullable=False),
        sa.Column("processed_elements", sa.Integer(), nullable=False),
        sa.Column("failed_elements", sa.Integer(), nullable=False),
        sa.Column("skipped_elements", sa.Integer(), nullable=False),
        sa.Column("normalized_elements", sa.Integer(), nullable=False),
        sa.Column("element_type_counts", _json_type(), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("layout_confidence", sa.Float(), nullable=True),
        sa.Column("warnings", _json_type(), nullable=False),
        sa.Column("errors", _json_type(), nullable=False),
        sa.Column("metadata", _json_type(), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name=op.f("fk_page_parse_reports_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("page_report_id", name=op.f("pk_page_parse_reports")),
        sa.UniqueConstraint(
            "tenant_id",
            "ingestion_run_id",
            "page_number",
            name="uq_page_parse_reports_run_page",
        ),
    )
    op.create_index(op.f("ix_page_parse_reports_tenant_id"), "page_parse_reports", ["tenant_id"])
    op.create_index(op.f("ix_page_parse_reports_document_id"), "page_parse_reports", ["document_id"])
    op.create_index(
        op.f("ix_page_parse_reports_ingestion_run_id"), "page_parse_reports", ["ingestion_run_id"]
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "element_parse_reports",
        sa.Column("element_report_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("element_id", sa.Uuid(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("normalized_element_type", sa.String(length=128), nullable=True),
        sa.Column("original_parser_element_type", sa.String(length=128), nullable=True),
        sa.Column("bbox", _json_type(), nullable=True),
        sa.Column("reading_order", sa.Integer(), nullable=True),
        sa.Column("parent_element_id", sa.Uuid(), nullable=True),
        sa.Column("section_path", _json_type(), nullable=False),
        sa.Column("detector", sa.String(length=128), nullable=True),
        sa.Column("parser_name", sa.String(length=128), nullable=True),
        sa.Column("parser_version", sa.String(length=128), nullable=True),
        sa.Column("processing_tool", sa.String(length=128), nullable=True),
        sa.Column("processing_stage", sa.String(length=128), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=128), nullable=True),
        sa.Column("input_ref", sa.Text(), nullable=True),
        sa.Column("output_ref", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("confidence_source", sa.String(length=128), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("quality_source", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("fallback_chain", _json_type(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("reached_normalized", sa.Boolean(), nullable=False),
        sa.Column("reached_chunking", sa.Boolean(), nullable=False),
        sa.Column("reached_vector_index", sa.Boolean(), nullable=False),
        sa.Column("reached_graph_index", sa.Boolean(), nullable=False),
        sa.Column("warning_code", sa.String(length=128), nullable=True),
        sa.Column("warning_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("content_loss_reason", sa.String(length=64), nullable=True),
        sa.Column("metadata", _json_type(), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name=op.f("fk_element_parse_reports_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("element_report_id", name=op.f("pk_element_parse_reports")),
    )
    for col in (
        "tenant_id",
        "document_id",
        "ingestion_run_id",
        "element_id",
        "page_number",
        "normalized_element_type",
        "parser_name",
        "model_name",
        "status",
        "content_loss_reason",
    ):
        op.create_index(op.f(f"ix_element_parse_reports_{col}"), "element_parse_reports", [col])

    created_at, updated_at = _timestamps()
    op.create_table(
        "processing_stage_runs",
        sa.Column("stage_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("stage_name", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("tool", sa.String(length=128), nullable=True),
        sa.Column("tool_version", sa.String(length=128), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("configuration", _json_type(), nullable=False),
        sa.Column("input_count", sa.Integer(), nullable=True),
        sa.Column("output_count", sa.Integer(), nullable=True),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("metadata", _json_type(), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name=op.f("fk_processing_stage_runs_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("stage_run_id", name=op.f("pk_processing_stage_runs")),
        sa.UniqueConstraint(
            "tenant_id",
            "ingestion_run_id",
            "stage_name",
            name="uq_processing_stage_runs_run_stage",
        ),
    )
    op.create_index(op.f("ix_processing_stage_runs_tenant_id"), "processing_stage_runs", ["tenant_id"])
    op.create_index(op.f("ix_processing_stage_runs_document_id"), "processing_stage_runs", ["document_id"])
    op.create_index(
        op.f("ix_processing_stage_runs_ingestion_run_id"),
        "processing_stage_runs",
        ["ingestion_run_id"],
    )
    op.create_index(op.f("ix_processing_stage_runs_stage_name"), "processing_stage_runs", ["stage_name"])

    created_at, updated_at = _timestamps()
    op.create_table(
        "parser_routing_decisions",
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("element_report_id", sa.Uuid(), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("selected_tool", sa.String(length=128), nullable=True),
        sa.Column("selected_model", sa.String(length=255), nullable=True),
        sa.Column("details", _json_type(), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name=op.f("fk_parser_routing_decisions_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("decision_id", name=op.f("pk_parser_routing_decisions")),
    )
    op.create_index(op.f("ix_parser_routing_decisions_tenant_id"), "parser_routing_decisions", ["tenant_id"])
    op.create_index(
        op.f("ix_parser_routing_decisions_document_id"), "parser_routing_decisions", ["document_id"]
    )
    op.create_index(
        op.f("ix_parser_routing_decisions_ingestion_run_id"),
        "parser_routing_decisions",
        ["ingestion_run_id"],
    )
    op.create_index(
        op.f("ix_parser_routing_decisions_reason_code"), "parser_routing_decisions", ["reason_code"]
    )

    created_at, updated_at = _timestamps()
    op.create_table(
        "ingestion_parse_issues",
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("element_report_id", sa.Uuid(), nullable=True),
        sa.Column("stage_name", sa.String(length=128), nullable=True),
        sa.Column("details", _json_type(), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name=op.f("fk_ingestion_parse_issues_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("issue_id", name=op.f("pk_ingestion_parse_issues")),
    )
    op.create_index(op.f("ix_ingestion_parse_issues_tenant_id"), "ingestion_parse_issues", ["tenant_id"])
    op.create_index(op.f("ix_ingestion_parse_issues_document_id"), "ingestion_parse_issues", ["document_id"])
    op.create_index(
        op.f("ix_ingestion_parse_issues_ingestion_run_id"),
        "ingestion_parse_issues",
        ["ingestion_run_id"],
    )
    op.create_index(op.f("ix_ingestion_parse_issues_severity"), "ingestion_parse_issues", ["severity"])

    created_at, updated_at = _timestamps()
    op.create_table(
        "content_loss_records",
        sa.Column("loss_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("element_report_id", sa.Uuid(), nullable=True),
        sa.Column("element_type", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", _json_type(), nullable=False),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.ingestion_run_id"],
            name=op.f("fk_content_loss_records_ingestion_run_id_ingestion_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("loss_id", name=op.f("pk_content_loss_records")),
    )
    op.create_index(op.f("ix_content_loss_records_tenant_id"), "content_loss_records", ["tenant_id"])
    op.create_index(op.f("ix_content_loss_records_document_id"), "content_loss_records", ["document_id"])
    op.create_index(
        op.f("ix_content_loss_records_ingestion_run_id"), "content_loss_records", ["ingestion_run_id"]
    )
    op.create_index(op.f("ix_content_loss_records_element_type"), "content_loss_records", ["element_type"])
    op.create_index(op.f("ix_content_loss_records_reason"), "content_loss_records", ["reason"])

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
    for table in reversed(TENANT_OWNED_TABLES):
        op.drop_table(table)
