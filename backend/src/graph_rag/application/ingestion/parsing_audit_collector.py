"""In-memory parsing audit collector flushed once per ingestion run."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from graph_rag.domain.parsing.audit import (
    ContentLossReason,
    ContentLossRecord,
    DocumentParseReport,
    ElementParseReport,
    ElementProcessingStatus,
    IngestionIssue,
    PageParseReport,
    PageProcessingStatus,
    ParsingAuditSnapshot,
    ProcessingStageRun,
    RoutingDecision,
    RoutingReasonCode,
    StageRunStatus,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _git_commit() -> str | None:
    return os.environ.get("GIT_COMMIT") or os.environ.get("SOURCE_COMMIT")


class ParsingAuditCollector:
    """Efficient event collector — no DB writes until ``build_snapshot`` / persist.

    Call sites should record coarse events; one batch flush at document completion
    keeps ingestion latency low.
    """

    def __init__(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        version_id: UUID,
        ingestion_run_id: UUID,
    ) -> None:
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.version_id = version_id
        self.ingestion_run_id = ingestion_run_id
        self.document = DocumentParseReport(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            ingestion_run_id=ingestion_run_id,
            started_at=_now(),
            app_version=os.environ.get("APP_VERSION", "0.1.0"),
            git_commit=_git_commit(),
        )
        self._pages: dict[int, PageParseReport] = {}
        self._elements: list[ElementParseReport] = []
        self._element_by_key: dict[tuple[int | None, str | None, int | None], ElementParseReport] = {}
        self._stages: dict[str, ProcessingStageRun] = {}
        self._stage_timers: dict[str, float] = {}
        self.routing_decisions: list[RoutingDecision] = []
        self.issues: list[IngestionIssue] = []
        self.content_losses: list[ContentLossRecord] = []

    def document_started(
        self,
        *,
        original_filename: str | None = None,
        file_hash: str | None = None,
        mime_type: str | None = None,
        file_size_bytes: int | None = None,
        config_profile: str | None = None,
        ocr_strategy: str | None = None,
        vision_strategy: str | None = None,
        embedding_model: str | None = None,
        text_llm: str | None = None,
        vision_llm: str | None = None,
    ) -> None:
        self.document.original_filename = original_filename
        self.document.file_hash = file_hash
        self.document.mime_type = mime_type
        self.document.file_size_bytes = file_size_bytes
        self.document.config_profile = config_profile
        self.document.ocr_strategy = ocr_strategy
        self.document.vision_strategy = vision_strategy
        self.document.embedding_model = embedding_model
        self.document.text_llm = text_llm
        self.document.vision_llm = vision_llm
        if self.document.started_at is None:
            self.document.started_at = _now()

    def record_routing(
        self,
        reason_code: RoutingReasonCode | str,
        *,
        message: str | None = None,
        selected_tool: str | None = None,
        selected_model: str | None = None,
        page_number: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        code = (
            reason_code
            if isinstance(reason_code, RoutingReasonCode)
            else RoutingReasonCode(str(reason_code))
        )
        self.routing_decisions.append(
            RoutingDecision(
                tenant_id=self.tenant_id,
                document_id=self.document_id,
                ingestion_run_id=self.ingestion_run_id,
                page_number=page_number,
                reason_code=code,
                message=message,
                selected_tool=selected_tool,
                selected_model=selected_model,
                details=dict(details or {}),
            )
        )

    def stage_started(
        self,
        stage_name: str,
        *,
        tool: str | None = None,
        tool_version: str | None = None,
        model_name: str | None = None,
        configuration: dict[str, Any] | None = None,
        input_count: int | None = None,
    ) -> None:
        self._stage_timers[stage_name] = time.perf_counter()
        self._stages[stage_name] = ProcessingStageRun(
            tenant_id=self.tenant_id,
            document_id=self.document_id,
            ingestion_run_id=self.ingestion_run_id,
            stage_name=stage_name,
            started_at=_now(),
            status=StageRunStatus.RUNNING,
            tool=tool,
            tool_version=tool_version,
            model_name=model_name,
            configuration=dict(configuration or {}),
            input_count=input_count,
        )

    def stage_completed(
        self,
        stage_name: str,
        *,
        status: StageRunStatus | str = StageRunStatus.COMPLETED,
        output_count: int | None = None,
        warning_count: int = 0,
        error_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        stage = self._stages.get(stage_name)
        if stage is None:
            self.stage_started(stage_name)
            stage = self._stages[stage_name]
        started = self._stage_timers.pop(stage_name, None)
        duration = None if started is None else (time.perf_counter() - started) * 1000.0
        status_enum = status if isinstance(status, StageRunStatus) else StageRunStatus(str(status))
        meta = dict(stage.metadata)
        if metadata:
            meta.update(metadata)
        self._stages[stage_name] = stage.model_copy(
            update={
                "completed_at": _now(),
                "duration_ms": duration,
                "status": status_enum,
                "output_count": output_count if output_count is not None else stage.output_count,
                "warning_count": warning_count,
                "error_count": error_count,
                "metadata": meta,
            }
        )

    def ensure_page(self, page_number: int) -> PageParseReport:
        page = self._pages.get(page_number)
        if page is None:
            page = PageParseReport(
                tenant_id=self.tenant_id,
                document_id=self.document_id,
                ingestion_run_id=self.ingestion_run_id,
                page_number=page_number,
                status=PageProcessingStatus.PROCESSING,
            )
            self._pages[page_number] = page
        return page

    def page_completed(
        self,
        page_number: int,
        *,
        status: PageProcessingStatus | str = PageProcessingStatus.PROCESSED,
        has_native_text: bool | None = None,
        ocr_required: bool | None = None,
        ocr_engine: str | None = None,
        page_parser: str | None = None,
        duration_ms: float | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> None:
        page = self.ensure_page(page_number)
        status_enum = (
            status if isinstance(status, PageProcessingStatus) else PageProcessingStatus(str(status))
        )
        self._pages[page_number] = page.model_copy(
            update={
                "status": status_enum,
                "has_native_text": has_native_text
                if has_native_text is not None
                else page.has_native_text,
                "ocr_required": ocr_required if ocr_required is not None else page.ocr_required,
                "ocr_engine": ocr_engine or page.ocr_engine,
                "page_parser": page_parser or page.page_parser,
                "duration_ms": duration_ms if duration_ms is not None else page.duration_ms,
                "warnings": list(warnings or page.warnings),
                "errors": list(errors or page.errors),
            }
        )

    def element_detected(
        self,
        *,
        page_number: int | None,
        normalized_element_type: str | None,
        original_parser_element_type: str | None = None,
        element_id: UUID | None = None,
        detector: str | None = None,
        parser_name: str | None = None,
        parser_version: str | None = None,
        reading_order: int | None = None,
        bbox: dict[str, float] | None = None,
        section_path: list[str] | None = None,
        confidence_score: float | None = None,
        confidence_source: str | None = None,
        status: ElementProcessingStatus = ElementProcessingStatus.DETECTED,
    ) -> ElementParseReport:
        report = ElementParseReport(
            tenant_id=self.tenant_id,
            document_id=self.document_id,
            ingestion_run_id=self.ingestion_run_id,
            element_id=element_id,
            page_number=page_number,
            normalized_element_type=normalized_element_type,
            original_parser_element_type=original_parser_element_type
            or normalized_element_type,
            bbox=bbox,
            reading_order=reading_order,
            section_path=list(section_path or []),
            detector=detector,
            parser_name=parser_name,
            parser_version=parser_version,
            confidence_score=confidence_score,
            confidence_source=confidence_source,
            status=status,
        )
        self._elements.append(report)
        key = (page_number, normalized_element_type, reading_order)
        self._element_by_key[key] = report
        if page_number is not None:
            page = self.ensure_page(page_number)
            counts = dict(page.element_type_counts)
            type_key = normalized_element_type or "unknown"
            counts[type_key] = counts.get(type_key, 0) + 1
            self._pages[page_number] = page.model_copy(
                update={
                    "detected_elements": page.detected_elements + 1,
                    "element_type_counts": counts,
                }
            )
        return report

    def update_element(
        self,
        report: ElementParseReport,
        **updates: Any,
    ) -> ElementParseReport:
        updated = report.model_copy(update=updates)
        for idx, existing in enumerate(self._elements):
            if existing.element_report_id == report.element_report_id:
                self._elements[idx] = updated
                break
        return updated

    def element_processed(
        self,
        report: ElementParseReport,
        *,
        processing_tool: str | None = None,
        model_name: str | None = None,
        status: ElementProcessingStatus = ElementProcessingStatus.PROCESSED,
        reached_normalized: bool = True,
        duration_ms: float | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> ElementParseReport:
        updated = self.update_element(
            report,
            processing_tool=processing_tool or report.processing_tool,
            model_name=model_name or report.model_name,
            status=status,
            reached_normalized=reached_normalized,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        if report.page_number is not None:
            page = self.ensure_page(report.page_number)
            self._pages[report.page_number] = page.model_copy(
                update={"processed_elements": page.processed_elements + 1}
            )
        return updated

    def element_skipped(
        self,
        report: ElementParseReport,
        *,
        skip_reason: str,
        content_loss_reason: ContentLossReason = ContentLossReason.INTENTIONALLY_SKIPPED,
        warning_code: str | None = None,
    ) -> ElementParseReport:
        updated = self.update_element(
            report,
            status=ElementProcessingStatus.SKIPPED,
            skip_reason=skip_reason,
            content_loss_reason=content_loss_reason,
            warning_code=warning_code,
            reached_normalized=False,
        )
        if report.page_number is not None:
            page = self.ensure_page(report.page_number)
            self._pages[report.page_number] = page.model_copy(
                update={"skipped_elements": page.skipped_elements + 1}
            )
        self.content_losses.append(
            ContentLossRecord(
                tenant_id=self.tenant_id,
                document_id=self.document_id,
                ingestion_run_id=self.ingestion_run_id,
                page_number=report.page_number,
                element_report_id=report.element_report_id,
                element_type=report.normalized_element_type,
                reason=content_loss_reason,
                message=skip_reason,
            )
        )
        return updated

    def element_failed(
        self,
        report: ElementParseReport,
        *,
        failure_reason: str,
        error_code: str | None = None,
        content_loss_reason: ContentLossReason = ContentLossReason.PARSING_FAILURE,
    ) -> ElementParseReport:
        updated = self.update_element(
            report,
            status=ElementProcessingStatus.FAILED,
            failure_reason=failure_reason,
            error_code=error_code,
            error_message=failure_reason,
            content_loss_reason=content_loss_reason,
            reached_normalized=False,
        )
        if report.page_number is not None:
            page = self.ensure_page(report.page_number)
            self._pages[report.page_number] = page.model_copy(
                update={"failed_elements": page.failed_elements + 1}
            )
        self.add_issue(
            severity="error",
            message=failure_reason,
            code=error_code,
            page_number=report.page_number,
            element_report_id=report.element_report_id,
        )
        self.content_losses.append(
            ContentLossRecord(
                tenant_id=self.tenant_id,
                document_id=self.document_id,
                ingestion_run_id=self.ingestion_run_id,
                page_number=report.page_number,
                element_report_id=report.element_report_id,
                element_type=report.normalized_element_type,
                reason=content_loss_reason,
                message=failure_reason,
            )
        )
        return updated

    def add_issue(
        self,
        *,
        severity: str,
        message: str,
        code: str | None = None,
        page_number: int | None = None,
        element_report_id: UUID | None = None,
        stage_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.issues.append(
            IngestionIssue(
                tenant_id=self.tenant_id,
                document_id=self.document_id,
                ingestion_run_id=self.ingestion_run_id,
                severity=severity,
                code=code,
                message=message,
                page_number=page_number,
                element_report_id=element_report_id,
                stage_name=stage_name,
                details=dict(details or {}),
            )
        )

    def mark_normalized(self, element_ids: set[UUID]) -> None:
        for report in list(self._elements):
            if report.element_id is not None and report.element_id in element_ids:
                self.update_element(
                    report,
                    reached_normalized=True,
                    status=(
                        report.status
                        if report.status
                        not in {
                            ElementProcessingStatus.DETECTED,
                            ElementProcessingStatus.QUEUED,
                            ElementProcessingStatus.PROCESSING,
                        }
                        else ElementProcessingStatus.PROCESSED
                    ),
                )

    def mark_downstream(
        self,
        *,
        chunking: bool = False,
        vector_index: bool = False,
        graph_index: bool = False,
    ) -> None:
        for report in list(self._elements):
            if not report.reached_normalized:
                continue
            self.update_element(
                report,
                reached_chunking=chunking or report.reached_chunking,
                reached_vector_index=vector_index or report.reached_vector_index,
                reached_graph_index=graph_index or report.reached_graph_index,
            )

    def reconcile_content_loss(self) -> None:
        """Flag detected elements that never reached normalized output."""
        known_loss_ids = {item.element_report_id for item in self.content_losses}
        for report in self._elements:
            if report.reached_normalized:
                continue
            if report.element_report_id in known_loss_ids:
                continue
            if report.status in {
                ElementProcessingStatus.SKIPPED,
                ElementProcessingStatus.FAILED,
                ElementProcessingStatus.UNSUPPORTED,
            }:
                continue
            reason = ContentLossReason.UNKNOWN_LOSS
            self.content_losses.append(
                ContentLossRecord(
                    tenant_id=self.tenant_id,
                    document_id=self.document_id,
                    ingestion_run_id=self.ingestion_run_id,
                    page_number=report.page_number,
                    element_report_id=report.element_report_id,
                    element_type=report.normalized_element_type,
                    reason=reason,
                    message="Detected element did not reach normalized document",
                )
            )
            self.update_element(
                report,
                content_loss_reason=reason,
                status=ElementProcessingStatus.FAILED
                if report.status is ElementProcessingStatus.DETECTED
                else report.status,
            )

    def document_completed(
        self,
        *,
        ingestion_status: str,
        primary_parser: str | None = None,
        parser_version: str | None = None,
        fallback_parsers: list[str] | None = None,
        total_pages: int | None = None,
        total_normalized_elements: int | None = None,
    ) -> ParsingAuditSnapshot:
        self.reconcile_content_loss()
        completed = _now()
        started = self.document.started_at or completed
        duration = (completed - started).total_seconds() * 1000.0

        detected = len(self._elements)
        processed = sum(
            1
            for item in self._elements
            if item.status
            in {
                ElementProcessingStatus.PROCESSED,
                ElementProcessingStatus.FALLBACK_PROCESSED,
                ElementProcessingStatus.PARTIALLY_PROCESSED,
            }
            or item.reached_normalized
        )
        failed = sum(
            1 for item in self._elements if item.status is ElementProcessingStatus.FAILED
        )
        skipped = sum(
            1
            for item in self._elements
            if item.status
            in {ElementProcessingStatus.SKIPPED, ElementProcessingStatus.UNSUPPORTED}
        )
        normalized = sum(1 for item in self._elements if item.reached_normalized)
        if total_normalized_elements is not None:
            normalized = total_normalized_elements

        # Roll page normalized counts from elements.
        by_page_norm: dict[int, int] = defaultdict(int)
        for item in self._elements:
            if item.reached_normalized and item.page_number is not None:
                by_page_norm[item.page_number] += 1
        for page_number, page in list(self._pages.items()):
            self._pages[page_number] = page.model_copy(
                update={"normalized_elements": by_page_norm.get(page_number, 0)}
            )

        coverage = (processed / detected) if detected else None
        norm_completeness = (normalized / detected) if detected else None

        self.document = self.document.model_copy(
            update={
                "completed_at": completed,
                "duration_ms": duration,
                "ingestion_status": ingestion_status,
                "primary_parser": primary_parser or self.document.primary_parser,
                "parser_version": parser_version or self.document.parser_version,
                "fallback_parsers": list(
                    fallback_parsers
                    if fallback_parsers is not None
                    else self.document.fallback_parsers
                ),
                "total_pages": (
                    total_pages
                    if total_pages is not None
                    else max(
                        max(self._pages.keys(), default=0),
                        max(
                            (el.page_number or 0 for el in self._elements),
                            default=0,
                        ),
                    )
                ),
                "total_detected_elements": detected,
                "total_processed_elements": processed,
                "total_failed_elements": failed,
                "total_skipped_elements": skipped,
                "total_normalized_elements": normalized,
                "total_warnings": sum(1 for i in self.issues if i.severity == "warning"),
                "total_errors": sum(1 for i in self.issues if i.severity == "error"),
                "element_processing_coverage": coverage,
                "normalization_completeness": norm_completeness,
                "extraction_completeness": norm_completeness,
            }
        )
        return ParsingAuditSnapshot(
            document=self.document,
            pages=sorted(self._pages.values(), key=lambda p: p.page_number),
            elements=list(self._elements),
            stages=list(self._stages.values()),
            routing_decisions=list(self.routing_decisions),
            issues=list(self.issues),
            content_losses=list(self.content_losses),
        )
