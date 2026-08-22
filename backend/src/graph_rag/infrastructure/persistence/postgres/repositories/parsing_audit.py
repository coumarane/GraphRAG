"""SQLAlchemy parsing audit repository — batch insert of immutable snapshots."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.postgres.models.parsing_audit import (
    ContentLossRecordModel,
    DocumentParseReportModel,
    ElementParseReportModel,
    IngestionIssueModel,
    PageParseReportModel,
    ProcessingStageRunModel,
    RoutingDecisionModel,
)
from graph_rag.infrastructure.persistence.postgres.rls import (
    require_matching_tenant,
    set_tenant_context,
)
from graph_rag.shared.exceptions import ConflictError


class SqlAlchemyParsingAuditRepository:
    """Persists full parsing audit snapshots in one flush."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_snapshot(
        self,
        tenant: TenantContext,
        snapshot: ParsingAuditSnapshot,
    ) -> ParsingAuditSnapshot:
        require_matching_tenant(tenant, snapshot.document.tenant_id)
        await set_tenant_context(self._session, tenant)
        existing = await self._session.scalar(
            select(DocumentParseReportModel.report_id).where(
                DocumentParseReportModel.tenant_id == tenant.tenant_id,
                DocumentParseReportModel.ingestion_run_id
                == snapshot.document.ingestion_run_id,
            )
        )
        if existing is not None:
            raise ConflictError(
                "Parse report already exists for ingestion run",
                details={"ingestion_run_id": str(snapshot.document.ingestion_run_id)},
            )

        doc = snapshot.document
        self._session.add(
            DocumentParseReportModel(
                report_id=doc.report_id,
                tenant_id=doc.tenant_id,
                document_id=doc.document_id,
                version_id=doc.version_id,
                ingestion_run_id=doc.ingestion_run_id,
                original_filename=doc.original_filename,
                file_hash=doc.file_hash,
                mime_type=doc.mime_type,
                file_size_bytes=doc.file_size_bytes,
                total_pages=doc.total_pages,
                started_at=doc.started_at,
                completed_at=doc.completed_at,
                duration_ms=doc.duration_ms,
                ingestion_status=doc.ingestion_status,
                primary_parser=doc.primary_parser,
                parser_version=doc.parser_version,
                fallback_parsers=list(doc.fallback_parsers),
                ocr_strategy=doc.ocr_strategy,
                vision_strategy=doc.vision_strategy,
                text_llm=doc.text_llm,
                vision_llm=doc.vision_llm,
                embedding_model=doc.embedding_model,
                config_profile=doc.config_profile,
                app_version=doc.app_version,
                git_commit=doc.git_commit,
                extraction_quality_score=doc.extraction_quality_score,
                extraction_completeness=doc.extraction_completeness,
                ocr_coverage=doc.ocr_coverage,
                element_processing_coverage=doc.element_processing_coverage,
                normalization_completeness=doc.normalization_completeness,
                total_detected_elements=doc.total_detected_elements,
                total_processed_elements=doc.total_processed_elements,
                total_failed_elements=doc.total_failed_elements,
                total_skipped_elements=doc.total_skipped_elements,
                total_normalized_elements=doc.total_normalized_elements,
                total_warnings=doc.total_warnings,
                total_errors=doc.total_errors,
                metadata_json=dict(doc.metadata),
            )
        )
        for page in snapshot.pages:
            self._session.add(self._page_model(page))
        for element in snapshot.elements:
            self._session.add(self._element_model(element))
        for stage in snapshot.stages:
            self._session.add(self._stage_model(stage))
        for decision in snapshot.routing_decisions:
            self._session.add(self._routing_model(decision))
        for issue in snapshot.issues:
            self._session.add(self._issue_model(issue))
        for loss in snapshot.content_losses:
            self._session.add(self._loss_model(loss))
        await self._session.flush()
        return snapshot

    async def get_snapshot(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        ingestion_run_id: UUID,
    ) -> ParsingAuditSnapshot | None:
        await set_tenant_context(self._session, tenant)
        doc_model = await self._session.scalar(
            select(DocumentParseReportModel).where(
                DocumentParseReportModel.tenant_id == tenant.tenant_id,
                DocumentParseReportModel.document_id == document_id,
                DocumentParseReportModel.ingestion_run_id == ingestion_run_id,
            )
        )
        if doc_model is None:
            return None
        pages = list(
            (
                await self._session.scalars(
                    select(PageParseReportModel)
                    .where(
                        PageParseReportModel.tenant_id == tenant.tenant_id,
                        PageParseReportModel.ingestion_run_id == ingestion_run_id,
                    )
                    .order_by(PageParseReportModel.page_number)
                )
            ).all()
        )
        elements = list(
            (
                await self._session.scalars(
                    select(ElementParseReportModel).where(
                        ElementParseReportModel.tenant_id == tenant.tenant_id,
                        ElementParseReportModel.ingestion_run_id == ingestion_run_id,
                    )
                )
            ).all()
        )
        stages = list(
            (
                await self._session.scalars(
                    select(ProcessingStageRunModel).where(
                        ProcessingStageRunModel.tenant_id == tenant.tenant_id,
                        ProcessingStageRunModel.ingestion_run_id == ingestion_run_id,
                    )
                )
            ).all()
        )
        routing = list(
            (
                await self._session.scalars(
                    select(RoutingDecisionModel).where(
                        RoutingDecisionModel.tenant_id == tenant.tenant_id,
                        RoutingDecisionModel.ingestion_run_id == ingestion_run_id,
                    )
                )
            ).all()
        )
        issues = list(
            (
                await self._session.scalars(
                    select(IngestionIssueModel).where(
                        IngestionIssueModel.tenant_id == tenant.tenant_id,
                        IngestionIssueModel.ingestion_run_id == ingestion_run_id,
                    )
                )
            ).all()
        )
        losses = list(
            (
                await self._session.scalars(
                    select(ContentLossRecordModel).where(
                        ContentLossRecordModel.tenant_id == tenant.tenant_id,
                        ContentLossRecordModel.ingestion_run_id == ingestion_run_id,
                    )
                )
            ).all()
        )
        return ParsingAuditSnapshot(
            document=self._doc_record(doc_model),
            pages=[self._page_record(p) for p in pages],
            elements=[self._element_record(e) for e in elements],
            stages=[self._stage_record(s) for s in stages],
            routing_decisions=[self._routing_record(r) for r in routing],
            issues=[self._issue_record(i) for i in issues],
            content_losses=[self._loss_record(x) for x in losses],
        )

    async def list_run_ids(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
    ) -> list[UUID]:
        await set_tenant_context(self._session, tenant)
        rows = await self._session.scalars(
            select(DocumentParseReportModel.ingestion_run_id).where(
                DocumentParseReportModel.tenant_id == tenant.tenant_id,
                DocumentParseReportModel.document_id == document_id,
            )
        )
        return sorted({row for row in rows}, key=str)

    @staticmethod
    def _page_model(page: PageParseReport) -> PageParseReportModel:
        return PageParseReportModel(
            page_report_id=page.page_report_id,
            tenant_id=page.tenant_id,
            document_id=page.document_id,
            ingestion_run_id=page.ingestion_run_id,
            page_number=page.page_number,
            page_width=page.page_width,
            page_height=page.page_height,
            has_native_text=page.has_native_text,
            ocr_required=page.ocr_required,
            ocr_engine=page.ocr_engine,
            page_parser=page.page_parser,
            fallback_parser=page.fallback_parser,
            status=page.status.value,
            duration_ms=page.duration_ms,
            detected_elements=page.detected_elements,
            processed_elements=page.processed_elements,
            failed_elements=page.failed_elements,
            skipped_elements=page.skipped_elements,
            normalized_elements=page.normalized_elements,
            element_type_counts=dict(page.element_type_counts),
            extraction_confidence=page.extraction_confidence,
            layout_confidence=page.layout_confidence,
            warnings=list(page.warnings),
            errors=list(page.errors),
            metadata_json=dict(page.metadata),
        )

    @staticmethod
    def _element_model(el: ElementParseReport) -> ElementParseReportModel:
        return ElementParseReportModel(
            element_report_id=el.element_report_id,
            tenant_id=el.tenant_id,
            document_id=el.document_id,
            ingestion_run_id=el.ingestion_run_id,
            element_id=el.element_id,
            page_number=el.page_number,
            normalized_element_type=el.normalized_element_type,
            original_parser_element_type=el.original_parser_element_type,
            bbox=dict(el.bbox) if el.bbox else None,
            reading_order=el.reading_order,
            parent_element_id=el.parent_element_id,
            section_path=list(el.section_path),
            detector=el.detector,
            parser_name=el.parser_name,
            parser_version=el.parser_version,
            processing_tool=el.processing_tool,
            processing_stage=el.processing_stage,
            model_name=el.model_name,
            model_version=el.model_version,
            prompt_version=el.prompt_version,
            input_ref=el.input_ref,
            output_ref=el.output_ref,
            confidence_score=el.confidence_score,
            confidence_source=el.confidence_source,
            quality_score=el.quality_score,
            quality_source=el.quality_source,
            duration_ms=el.duration_ms,
            prompt_tokens=el.prompt_tokens,
            completion_tokens=el.completion_tokens,
            total_tokens=el.total_tokens,
            retry_count=el.retry_count,
            fallback_chain=list(el.fallback_chain),
            status=el.status.value,
            reached_normalized=el.reached_normalized,
            reached_chunking=el.reached_chunking,
            reached_vector_index=el.reached_vector_index,
            reached_graph_index=el.reached_graph_index,
            warning_code=el.warning_code,
            warning_message=el.warning_message,
            error_code=el.error_code,
            error_message=el.error_message,
            skip_reason=el.skip_reason,
            failure_reason=el.failure_reason,
            content_loss_reason=(
                el.content_loss_reason.value if el.content_loss_reason else None
            ),
            metadata_json=dict(el.metadata),
        )

    @staticmethod
    def _stage_model(stage: ProcessingStageRun) -> ProcessingStageRunModel:
        return ProcessingStageRunModel(
            stage_run_id=stage.stage_run_id,
            tenant_id=stage.tenant_id,
            document_id=stage.document_id,
            ingestion_run_id=stage.ingestion_run_id,
            stage_name=stage.stage_name,
            started_at=stage.started_at,
            completed_at=stage.completed_at,
            duration_ms=stage.duration_ms,
            status=stage.status.value,
            tool=stage.tool,
            tool_version=stage.tool_version,
            model_name=stage.model_name,
            model_version=stage.model_version,
            configuration=dict(stage.configuration),
            input_count=stage.input_count,
            output_count=stage.output_count,
            warning_count=stage.warning_count,
            error_count=stage.error_count,
            metadata_json=dict(stage.metadata),
        )

    @staticmethod
    def _routing_model(item: RoutingDecision) -> RoutingDecisionModel:
        return RoutingDecisionModel(
            decision_id=item.decision_id,
            tenant_id=item.tenant_id,
            document_id=item.document_id,
            ingestion_run_id=item.ingestion_run_id,
            page_number=item.page_number,
            element_report_id=item.element_report_id,
            reason_code=item.reason_code.value,
            message=item.message,
            selected_tool=item.selected_tool,
            selected_model=item.selected_model,
            details=dict(item.details),
        )

    @staticmethod
    def _issue_model(item: IngestionIssue) -> IngestionIssueModel:
        return IngestionIssueModel(
            issue_id=item.issue_id,
            tenant_id=item.tenant_id,
            document_id=item.document_id,
            ingestion_run_id=item.ingestion_run_id,
            severity=item.severity,
            code=item.code,
            message=item.message,
            page_number=item.page_number,
            element_report_id=item.element_report_id,
            stage_name=item.stage_name,
            details=dict(item.details),
        )

    @staticmethod
    def _loss_model(item: ContentLossRecord) -> ContentLossRecordModel:
        return ContentLossRecordModel(
            loss_id=item.loss_id,
            tenant_id=item.tenant_id,
            document_id=item.document_id,
            ingestion_run_id=item.ingestion_run_id,
            page_number=item.page_number,
            element_report_id=item.element_report_id,
            element_type=item.element_type,
            reason=item.reason.value,
            message=item.message,
            details=dict(item.details),
        )

    @staticmethod
    def _doc_record(model: DocumentParseReportModel) -> DocumentParseReport:
        return DocumentParseReport(
            report_id=model.report_id,
            tenant_id=model.tenant_id,
            document_id=model.document_id,
            version_id=model.version_id,
            ingestion_run_id=model.ingestion_run_id,
            original_filename=model.original_filename,
            file_hash=model.file_hash,
            mime_type=model.mime_type,
            file_size_bytes=model.file_size_bytes,
            total_pages=model.total_pages,
            started_at=model.started_at,
            completed_at=model.completed_at,
            duration_ms=model.duration_ms,
            ingestion_status=model.ingestion_status,
            primary_parser=model.primary_parser,
            parser_version=model.parser_version,
            fallback_parsers=list(model.fallback_parsers or []),
            ocr_strategy=model.ocr_strategy,
            vision_strategy=model.vision_strategy,
            text_llm=model.text_llm,
            vision_llm=model.vision_llm,
            embedding_model=model.embedding_model,
            config_profile=model.config_profile,
            app_version=model.app_version,
            git_commit=model.git_commit,
            extraction_quality_score=model.extraction_quality_score,
            extraction_completeness=model.extraction_completeness,
            ocr_coverage=model.ocr_coverage,
            element_processing_coverage=model.element_processing_coverage,
            normalization_completeness=model.normalization_completeness,
            total_detected_elements=model.total_detected_elements,
            total_processed_elements=model.total_processed_elements,
            total_failed_elements=model.total_failed_elements,
            total_skipped_elements=model.total_skipped_elements,
            total_normalized_elements=model.total_normalized_elements,
            total_warnings=model.total_warnings,
            total_errors=model.total_errors,
            metadata=dict(model.metadata_json or {}),
        )

    @staticmethod
    def _page_record(model: PageParseReportModel) -> PageParseReport:
        return PageParseReport(
            page_report_id=model.page_report_id,
            tenant_id=model.tenant_id,
            document_id=model.document_id,
            ingestion_run_id=model.ingestion_run_id,
            page_number=model.page_number,
            page_width=model.page_width,
            page_height=model.page_height,
            has_native_text=model.has_native_text,
            ocr_required=model.ocr_required,
            ocr_engine=model.ocr_engine,
            page_parser=model.page_parser,
            fallback_parser=model.fallback_parser,
            status=PageProcessingStatus(model.status),
            duration_ms=model.duration_ms,
            detected_elements=model.detected_elements,
            processed_elements=model.processed_elements,
            failed_elements=model.failed_elements,
            skipped_elements=model.skipped_elements,
            normalized_elements=model.normalized_elements,
            element_type_counts=dict(model.element_type_counts or {}),
            extraction_confidence=model.extraction_confidence,
            layout_confidence=model.layout_confidence,
            warnings=list(model.warnings or []),
            errors=list(model.errors or []),
            metadata=dict(model.metadata_json or {}),
        )

    @staticmethod
    def _element_record(model: ElementParseReportModel) -> ElementParseReport:
        return ElementParseReport(
            element_report_id=model.element_report_id,
            tenant_id=model.tenant_id,
            document_id=model.document_id,
            ingestion_run_id=model.ingestion_run_id,
            element_id=model.element_id,
            page_number=model.page_number,
            normalized_element_type=model.normalized_element_type,
            original_parser_element_type=model.original_parser_element_type,
            bbox=dict(model.bbox) if model.bbox else None,
            reading_order=model.reading_order,
            parent_element_id=model.parent_element_id,
            section_path=list(model.section_path or []),
            detector=model.detector,
            parser_name=model.parser_name,
            parser_version=model.parser_version,
            processing_tool=model.processing_tool,
            processing_stage=model.processing_stage,
            model_name=model.model_name,
            model_version=model.model_version,
            prompt_version=model.prompt_version,
            input_ref=model.input_ref,
            output_ref=model.output_ref,
            confidence_score=model.confidence_score,
            confidence_source=model.confidence_source,
            quality_score=model.quality_score,
            quality_source=model.quality_source,
            duration_ms=model.duration_ms,
            prompt_tokens=model.prompt_tokens,
            completion_tokens=model.completion_tokens,
            total_tokens=model.total_tokens,
            retry_count=model.retry_count,
            fallback_chain=list(model.fallback_chain or []),
            status=ElementProcessingStatus(model.status),
            reached_normalized=model.reached_normalized,
            reached_chunking=model.reached_chunking,
            reached_vector_index=model.reached_vector_index,
            reached_graph_index=model.reached_graph_index,
            warning_code=model.warning_code,
            warning_message=model.warning_message,
            error_code=model.error_code,
            error_message=model.error_message,
            skip_reason=model.skip_reason,
            failure_reason=model.failure_reason,
            content_loss_reason=(
                ContentLossReason(model.content_loss_reason)
                if model.content_loss_reason
                else None
            ),
            metadata=dict(model.metadata_json or {}),
        )

    @staticmethod
    def _stage_record(model: ProcessingStageRunModel) -> ProcessingStageRun:
        return ProcessingStageRun(
            stage_run_id=model.stage_run_id,
            tenant_id=model.tenant_id,
            document_id=model.document_id,
            ingestion_run_id=model.ingestion_run_id,
            stage_name=model.stage_name,
            started_at=model.started_at,
            completed_at=model.completed_at,
            duration_ms=model.duration_ms,
            status=StageRunStatus(model.status),
            tool=model.tool,
            tool_version=model.tool_version,
            model_name=model.model_name,
            model_version=model.model_version,
            configuration=dict(model.configuration or {}),
            input_count=model.input_count,
            output_count=model.output_count,
            warning_count=model.warning_count,
            error_count=model.error_count,
            metadata=dict(model.metadata_json or {}),
        )

    @staticmethod
    def _routing_record(model: RoutingDecisionModel) -> RoutingDecision:
        return RoutingDecision(
            decision_id=model.decision_id,
            tenant_id=model.tenant_id,
            document_id=model.document_id,
            ingestion_run_id=model.ingestion_run_id,
            page_number=model.page_number,
            element_report_id=model.element_report_id,
            reason_code=RoutingReasonCode(model.reason_code),
            message=model.message,
            selected_tool=model.selected_tool,
            selected_model=model.selected_model,
            details=dict(model.details or {}),
        )

    @staticmethod
    def _issue_record(model: IngestionIssueModel) -> IngestionIssue:
        return IngestionIssue(
            issue_id=model.issue_id,
            tenant_id=model.tenant_id,
            document_id=model.document_id,
            ingestion_run_id=model.ingestion_run_id,
            severity=model.severity,
            code=model.code,
            message=model.message,
            page_number=model.page_number,
            element_report_id=model.element_report_id,
            stage_name=model.stage_name,
            details=dict(model.details or {}),
        )

    @staticmethod
    def _loss_record(model: ContentLossRecordModel) -> ContentLossRecord:
        return ContentLossRecord(
            loss_id=model.loss_id,
            tenant_id=model.tenant_id,
            document_id=model.document_id,
            ingestion_run_id=model.ingestion_run_id,
            page_number=model.page_number,
            element_report_id=model.element_report_id,
            element_type=model.element_type,
            reason=ContentLossReason(model.reason),
            message=model.message,
            details=dict(model.details or {}),
        )
