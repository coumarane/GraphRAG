"""ORM models for structured parsing audit reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from graph_rag.domain.ids import new_id
from graph_rag.infrastructure.persistence.postgres.base import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
)


class DocumentParseReportModel(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "document_parse_reports"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "ingestion_run_id",
            name="uq_document_parse_reports_tenant_run",
        ),
    )

    report_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.version_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    ingestion_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_parser: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fallback_parsers: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    ocr_strategy: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vision_strategy: Mapped[str | None] = mapped_column(String(128), nullable=True)
    text_llm: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vision_llm: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config_profile: Mapped[str | None] = mapped_column(String(128), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    extraction_completeness: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    element_processing_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalization_completeness: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_detected_elements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_processed_elements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_failed_elements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_skipped_elements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_normalized_elements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_warnings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", nullable=False, default=dict)


class PageParseReportModel(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "page_parse_reports"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "ingestion_run_id",
            "page_number",
            name="uq_page_parse_reports_run_page",
        ),
    )

    page_report_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    page_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_native_text: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ocr_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ocr_engine: Mapped[str | None] = mapped_column(String(128), nullable=True)
    page_parser: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fallback_parser: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    detected_elements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_elements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_elements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_elements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    normalized_elements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    element_type_counts: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    layout_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    warnings: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    errors: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", nullable=False, default=dict)


class ElementParseReportModel(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "element_parse_reports"

    element_report_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    element_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    normalized_element_type: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    original_parser_element_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    reading_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_element_id: Mapped[UUID | None] = mapped_column(nullable=True)
    section_path: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    detector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parser_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    parser_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processing_tool: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processing_stage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_chain: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="detected", index=True)
    reached_normalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reached_chunking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reached_vector_index: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reached_graph_index: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    warning_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    warning_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_loss_reason: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", nullable=False, default=dict)


class ProcessingStageRunModel(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "processing_stage_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "ingestion_run_id",
            "stage_name",
            name="uq_processing_stage_runs_run_stage",
        ),
    )

    stage_run_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    tool: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    input_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", nullable=False, default=dict)


class RoutingDecisionModel(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "parser_routing_decisions"

    decision_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    element_report_id: Mapped[UUID | None] = mapped_column(nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_tool: Mapped[str | None] = mapped_column(String(128), nullable=True)
    selected_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)


class IngestionIssueModel(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "ingestion_parse_issues"

    issue_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    severity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    element_report_id: Mapped[UUID | None] = mapped_column(nullable=True)
    stage_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)


class ContentLossRecordModel(Base, TimestampMixin, TenantOwnedMixin):
    __tablename__ = "content_loss_records"

    loss_id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ingestion_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("ingestion_runs.ingestion_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    element_report_id: Mapped[UUID | None] = mapped_column(nullable=True)
    element_type: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
