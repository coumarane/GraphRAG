"""Structured document parsing audit models (immutable per ingestion run).

These records answer content-level questions (what existed, who processed it,
what was lost and why) separately from technical application logs.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.ids import new_id
from graph_rag.domain.types import JsonValue


class ElementProcessingStatus(StrEnum):
    """Controlled element processing states."""

    DETECTED = "detected"
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    PARTIALLY_PROCESSED = "partially_processed"
    SKIPPED = "skipped"
    FAILED = "failed"
    FALLBACK_PROCESSED = "fallback_processed"
    UNSUPPORTED = "unsupported"


class PageProcessingStatus(StrEnum):
    """Page-level processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    PARTIALLY_PROCESSED = "partially_processed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageRunStatus(StrEnum):
    """Pipeline stage audit status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    SKIPPED = "skipped"


class ContentLossReason(StrEnum):
    """Why detected content did not reach normalized output."""

    INTENTIONALLY_SKIPPED = "intentionally_skipped"
    UNSUPPORTED = "unsupported"
    PARSING_FAILURE = "parsing_failure"
    FILTERING = "filtering"
    DEDUPLICATION = "deduplication"
    LOW_CONFIDENCE_REJECTION = "low_confidence_rejection"
    PROCESSING_DISABLED = "processing_disabled"
    UNKNOWN_LOSS = "unknown_loss"


class RoutingReasonCode(StrEnum):
    """Machine-readable parser/model routing decisions."""

    PRIMARY_PARSER_SELECTED = "PRIMARY_PARSER_SELECTED"
    NO_NATIVE_TEXT = "NO_NATIVE_TEXT"
    OCR_REQUIRED = "OCR_REQUIRED"
    TABLE_EXTRACTION_FAILED = "TABLE_EXTRACTION_FAILED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    VISION_REQUIRED = "VISION_REQUIRED"
    UNSUPPORTED_ELEMENT = "UNSUPPORTED_ELEMENT"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    FALLBACK_TRIGGERED = "FALLBACK_TRIGGERED"
    QUALITY_THRESHOLD_FAILED = "QUALITY_THRESHOLD_FAILED"
    MODEL_ERROR = "MODEL_ERROR"
    TIMEOUT = "TIMEOUT"
    TOKEN_LIMIT = "TOKEN_LIMIT"
    RATE_LIMIT = "RATE_LIMIT"
    PARSER_OVERRIDE = "PARSER_OVERRIDE"
    PROFILE_ROUTE = "PROFILE_ROUTE"


class DocumentParseReport(BaseModel):
    """Document-level immutable parse report for one ingestion run."""

    model_config = ConfigDict(extra="forbid")

    report_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    ingestion_run_id: UUID
    original_filename: str | None = None
    file_hash: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    total_pages: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = None
    ingestion_status: str | None = None
    primary_parser: str | None = None
    parser_version: str | None = None
    fallback_parsers: list[str] = Field(default_factory=list)
    ocr_strategy: str | None = None
    vision_strategy: str | None = None
    text_llm: str | None = None
    vision_llm: str | None = None
    embedding_model: str | None = None
    config_profile: str | None = None
    app_version: str | None = None
    git_commit: str | None = None
    extraction_quality_score: float | None = None
    extraction_completeness: float | None = None
    ocr_coverage: float | None = None
    element_processing_coverage: float | None = None
    normalization_completeness: float | None = None
    total_detected_elements: int = 0
    total_processed_elements: int = 0
    total_failed_elements: int = 0
    total_skipped_elements: int = 0
    total_normalized_elements: int = 0
    total_warnings: int = 0
    total_errors: int = 0
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class PageParseReport(BaseModel):
    """Page-level parse report."""

    model_config = ConfigDict(extra="forbid")

    page_report_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    document_id: UUID
    ingestion_run_id: UUID
    page_number: int = Field(ge=1)
    page_width: float | None = None
    page_height: float | None = None
    has_native_text: bool | None = None
    ocr_required: bool | None = None
    ocr_engine: str | None = None
    page_parser: str | None = None
    fallback_parser: str | None = None
    status: PageProcessingStatus = PageProcessingStatus.PENDING
    duration_ms: float | None = None
    detected_elements: int = 0
    processed_elements: int = 0
    failed_elements: int = 0
    skipped_elements: int = 0
    normalized_elements: int = 0
    element_type_counts: dict[str, int] = Field(default_factory=dict)
    extraction_confidence: float | None = None
    layout_confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ElementParseReport(BaseModel):
    """Element-level audit record with processing provenance."""

    model_config = ConfigDict(extra="forbid")

    element_report_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    document_id: UUID
    ingestion_run_id: UUID
    element_id: UUID | None = None
    page_number: int | None = None
    normalized_element_type: str | None = None
    original_parser_element_type: str | None = None
    bbox: dict[str, float] | None = None
    reading_order: int | None = None
    parent_element_id: UUID | None = None
    section_path: list[str] = Field(default_factory=list)
    detector: str | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    processing_tool: str | None = None
    processing_stage: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    input_ref: str | None = None
    output_ref: str | None = None
    confidence_score: float | None = None
    confidence_source: str | None = None
    quality_score: float | None = None
    quality_source: str | None = None
    duration_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    retry_count: int = 0
    fallback_chain: list[str] = Field(default_factory=list)
    status: ElementProcessingStatus = ElementProcessingStatus.DETECTED
    reached_normalized: bool = False
    reached_chunking: bool = False
    reached_vector_index: bool = False
    reached_graph_index: bool = False
    warning_code: str | None = None
    warning_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    skip_reason: str | None = None
    failure_reason: str | None = None
    content_loss_reason: ContentLossReason | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ProcessingStageRun(BaseModel):
    """Independent pipeline stage timing/tool audit."""

    model_config = ConfigDict(extra="forbid")

    stage_run_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    document_id: UUID
    ingestion_run_id: UUID
    stage_name: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = None
    status: StageRunStatus = StageRunStatus.PENDING
    tool: str | None = None
    tool_version: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    configuration: dict[str, JsonValue] = Field(default_factory=dict)
    input_count: int | None = None
    output_count: int | None = None
    warning_count: int = 0
    error_count: int = 0
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RoutingDecision(BaseModel):
    """Why a parser/model/tool was selected."""

    model_config = ConfigDict(extra="forbid")

    decision_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    document_id: UUID
    ingestion_run_id: UUID
    page_number: int | None = None
    element_report_id: UUID | None = None
    reason_code: RoutingReasonCode
    message: str | None = None
    selected_tool: str | None = None
    selected_model: str | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class IngestionIssue(BaseModel):
    """Warning or error attached to a parse report."""

    model_config = ConfigDict(extra="forbid")

    issue_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    document_id: UUID
    ingestion_run_id: UUID
    severity: str  # warning | error
    code: str | None = None
    message: str
    page_number: int | None = None
    element_report_id: UUID | None = None
    stage_name: str | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ContentLossRecord(BaseModel):
    """Detected content that did not reach normalized output."""

    model_config = ConfigDict(extra="forbid")

    loss_id: UUID = Field(default_factory=new_id)
    tenant_id: UUID
    document_id: UUID
    ingestion_run_id: UUID
    page_number: int | None = None
    element_report_id: UUID | None = None
    element_type: str | None = None
    reason: ContentLossReason
    message: str | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ParsingAuditSnapshot(BaseModel):
    """Full immutable audit payload for one ingestion run."""

    model_config = ConfigDict(extra="forbid")

    document: DocumentParseReport
    pages: list[PageParseReport] = Field(default_factory=list)
    elements: list[ElementParseReport] = Field(default_factory=list)
    stages: list[ProcessingStageRun] = Field(default_factory=list)
    routing_decisions: list[RoutingDecision] = Field(default_factory=list)
    issues: list[IngestionIssue] = Field(default_factory=list)
    content_losses: list[ContentLossRecord] = Field(default_factory=list)
