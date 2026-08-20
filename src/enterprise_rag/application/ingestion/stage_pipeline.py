"""Resumable, idempotent document ingestion stages backed by object-store artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from enterprise_rag.application.chunking import EmbedChunksService, HierarchicalMultimodalChunker
from enterprise_rag.application.graph.build_graph import BuildKnowledgeGraphService
from enterprise_rag.application.ingestion.handlers import CallableStageHandler
from enterprise_rag.application.ingestion.local_pipeline import (
    _STRUCTURED_PARSERS,
    ProcessRegisteredDocumentService,
    _parse_document_raw,
    _stamp_hybrid_vision_provenance,
    _vision_enrich_pages,
    resolve_model_label,
)
from enterprise_rag.application.ingestion.orchestrator import (
    IngestionOrchestrator,
    OrchestrationResult,
)
from enterprise_rag.application.ingestion.parsing_audit_collector import ParsingAuditCollector
from enterprise_rag.application.ingestion.visual_enrichment import collect_visual_targets
from enterprise_rag.application.usage.context import usage_context
from enterprise_rag.config.settings import get_settings
from enterprise_rag.domain.chunks.models import ChunkBase
from enterprise_rag.domain.chunks.vectors import ChunkingResult, ChunkVectorRecord
from enterprise_rag.domain.documents.document import NormalizedDocument
from enterprise_rag.domain.graph.structural import StructuralGraphBuilder
from enterprise_rag.domain.ids import content_sha256_hex, deterministic_id
from enterprise_rag.domain.ingestion.handlers import StageContext, StageOutcome, StageOutcomeStatus
from enterprise_rag.domain.ingestion.records import ParserAttemptRecord
from enterprise_rag.domain.ingestion.retry import RetryPolicy
from enterprise_rag.domain.ingestion.stages import (
    INGESTION_STAGE_ORDER,
    SUCCESSFUL_RUN_STATUSES,
    DocumentLifecycleStatus,
    IngestionRunStatus,
    IngestionStageName,
)
from enterprise_rag.domain.ingestion.state_machine import IngestionProgress
from enterprise_rag.domain.parsing.audit import (
    ElementProcessingStatus,
    RoutingReasonCode,
    StageRunStatus,
)
from enterprise_rag.domain.parsing.normalize import normalize_parser_result
from enterprise_rag.domain.parsing.types import ParserName, ParseSource, RawParserResult
from enterprise_rag.domain.storage.protocols import version_prefix
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import NotFoundError, PermanentError
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)


def _artifact_key(tenant_id: UUID, document_id: UUID, version_id: UUID, name: str) -> str:
    prefix = version_prefix(tenant_id=tenant_id, document_id=document_id, version_id=version_id)
    return f"{prefix}artifacts/{name}.json"


class PipelineWorkspace:
    """In-process + object-store state for one ingestion run."""

    def __init__(self, service: ProcessRegisteredDocumentService) -> None:
        self.service = service
        self.tenant: TenantContext | None = None
        self.run: Any = None
        self.version: Any = None
        self.document: Any = None
        self.data: bytes | None = None
        self.filename: str = ""
        self.mime: str = ""
        self.audit: ParsingAuditCollector | None = None
        self.raw: RawParserResult | None = None
        self.normalized: NormalizedDocument | None = None
        self.chunks: list[ChunkBase] = []
        self.embedded: list[ChunkVectorRecord] = []
        self.selected_parser: str | None = None
        self.used_parser: str | None = None
        self.attempted: list[str] = []
        self.fallbacks: list[str] = []
        self.vision_failed: int = 0
        self.vision_target_count: int = 0
        self.graph_counts: dict[str, int] = {}
        self.needs_review: bool = False

    def _key(self, name: str) -> str:
        assert self.tenant is not None and self.run is not None
        return _artifact_key(
            self.tenant.tenant_id,
            self.run.document_id,
            self.run.version_id,
            name,
        )

    async def save_json(self, name: str, payload: dict[str, Any]) -> None:
        assert self.tenant is not None
        raw = json.dumps(payload, default=str).encode("utf-8")
        await self.service.object_store.put_bytes(
            self.tenant,
            object_key=self._key(name),
            data=raw,
            content_type="application/json",
            content_hash=content_sha256_hex(raw),
        )

    async def load_json(self, name: str) -> dict[str, Any] | None:
        assert self.tenant is not None
        try:
            data = await self.service.object_store.get_bytes(
                self.tenant, object_key=self._key(name)
            )
        except NotFoundError:
            return None
        return json.loads(data.decode("utf-8"))


class DocumentPipeline:
    """Stage handlers that resume from the first incomplete stage."""

    def __init__(self, workspace: PipelineWorkspace) -> None:
        self.w = workspace

    def handlers(self) -> dict[IngestionStageName, CallableStageHandler]:
        mapping: dict[IngestionStageName, CallableStageHandler] = {}
        for stage in INGESTION_STAGE_ORDER:
            mapping[stage] = CallableStageHandler(stage, self._method_for(stage))
        return mapping

    def _method_for(self, stage: IngestionStageName):
        table = {
            IngestionStageName.VALIDATE: self.stage_preregistered,
            IngestionStageName.HASH: self.stage_preregistered,
            IngestionStageName.REGISTER_DOCUMENT: self.stage_preregistered,
            IngestionStageName.STORE_ORIGINAL: self.stage_preregistered,
            IngestionStageName.INSPECT: self.stage_inspect,
            IngestionStageName.SELECT_PARSER: self.stage_select_parser,
            IngestionStageName.PARSE: self.stage_parse,
            IngestionStageName.NORMALIZE: self.stage_normalize,
            IngestionStageName.STORE_ELEMENTS: self.stage_store_elements,
            IngestionStageName.EXTRACT_ASSETS: self.stage_skip_assets,
            IngestionStageName.ENRICH_IMAGES: self.stage_enrich_images,
            IngestionStageName.ENRICH_TABLES: self.stage_skip_optional,
            IngestionStageName.ENRICH_EQUATIONS: self.stage_skip_optional,
            IngestionStageName.BUILD_CONTEXT: self.stage_skip_optional,
            IngestionStageName.CHUNK: self.stage_chunk,
            IngestionStageName.EMBED: self.stage_embed,
            IngestionStageName.INDEX_VECTOR: self.stage_index_vector,
            IngestionStageName.EXTRACT_GRAPH: self.stage_extract_graph,
            IngestionStageName.RESOLVE_ENTITIES: self.stage_skip_optional,
            IngestionStageName.INDEX_GRAPH: self.stage_index_graph,
            IngestionStageName.SUMMARIZE_COMMUNITIES: self.stage_skip_communities,
            IngestionStageName.FINALIZE: self.stage_finalize,
        }
        return table[stage]

    async def ensure_loaded(self, context: StageContext) -> None:
        w = self.w
        if w.tenant is None:
            w.tenant = context.tenant
        if w.run is None:
            w.run = await w.service.ingestion_repo.get_run(context.tenant, context.ingestion_run_id)
        if w.version is None:
            w.version = await w.service.document_repo.get_version(
                context.tenant, context.version_id
            )
            if w.version is None or not w.version.original_object_key:
                raise PermanentError(
                    "Document version or object key missing",
                    code="missing_original",
                )
        if w.data is None:
            w.data = await w.service.object_store.get_bytes(
                context.tenant, object_key=w.version.original_object_key
            )
            w.filename = w.version.source_filename or Path(w.version.original_object_key).name
            w.mime = (w.version.mime_type or "").lower()
        if w.document is None:
            w.document = await w.service.document_repo.get_document(
                context.tenant, context.document_id
            )
        if w.audit is None:
            w.audit = ParsingAuditCollector(
                tenant_id=context.tenant.tenant_id,
                document_id=context.document_id,
                version_id=context.version_id,
                ingestion_run_id=context.ingestion_run_id,
            )
            w.audit.document_started(
                original_filename=w.filename,
                file_hash=w.version.content_hash,
                mime_type=w.version.mime_type,
                file_size_bytes=w.version.byte_size,
                config_profile="local_pipeline",
                ocr_strategy="auto",
                vision_strategy="per_element_vision" if w.service.chat_model else "disabled",
                embedding_model=resolve_model_label(w.service.embedding_model),
                text_llm=resolve_model_label(w.service.chat_model),
                vision_llm=resolve_model_label(w.service.chat_model),
            )
        if w.raw is None:
            stored = await w.load_json("parse_raw")
            if stored:
                w.raw = RawParserResult.model_validate(stored["raw"])
                w.selected_parser = stored.get("selected_parser")
                w.used_parser = stored.get("used_parser")
                w.attempted = list(stored.get("attempted") or [])
                w.fallbacks = list(stored.get("fallbacks") or [])
                w.vision_failed = int(stored.get("vision_failed") or 0)
                w.vision_target_count = int(stored.get("vision_target_count") or 0)
        if w.normalized is None:
            stored = await w.load_json("normalized")
            if stored:
                w.normalized = NormalizedDocument.model_validate(stored)
        if not w.chunks:
            stored = await w.load_json("chunks")
            if stored:
                w.chunks = [ChunkBase.model_validate(item) for item in stored.get("chunks") or []]
        if not w.embedded:
            stored = await w.load_json("embeddings")
            if stored:
                w.embedded = [
                    ChunkVectorRecord.model_validate(item) for item in stored.get("records") or []
                ]

    async def stage_preregistered(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        return StageOutcome(status=StageOutcomeStatus.COMPLETED)

    async def stage_inspect(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        page_count = w.version.page_count or 0
        await w.save_json(
            "inspect",
            {
                "mime": w.mime,
                "filename": w.filename,
                "byte_size": w.version.byte_size,
                "page_count": page_count,
            },
        )
        return StageOutcome(status=StageOutcomeStatus.COMPLETED, pages_processed=page_count or None)

    async def stage_select_parser(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        stored = await w.load_json("parser_selection")
        if stored:
            w.selected_parser = stored.get("selected_parser")
            return StageOutcome(status=StageOutcomeStatus.COMPLETED)
        requested = w.run.parser_requested if w.run else None
        selected = ParserName.DOCLING.value
        reason = "selection_occurs_at_parse"
        if requested and requested not in {"auto", None}:
            selected = str(requested)
            reason = "parser_override"
        w.selected_parser = selected
        await w.save_json("parser_selection", {"selected_parser": selected, "reason": reason})
        if w.run is not None:
            w.run.latest_warning = f"selected={selected}; {reason}"
            await w.service.ingestion_repo.update_run(context.tenant, w.run)
        return StageOutcome(status=StageOutcomeStatus.COMPLETED)

    async def stage_parse(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        assert w.audit is not None and w.data is not None and w.run is not None
        if w.raw is not None:
            return StageOutcome(
                status=StageOutcomeStatus.COMPLETED,
                pages_processed=w.raw.page_count,
                elements_processed=len(w.raw.elements),
            )
        w.audit.stage_started("PARSE", tool="parser_registry", input_count=1)
        outcome = await _parse_document_raw(
            data=w.data,
            filename=w.filename,
            mime_type=w.version.mime_type or "application/octet-stream",
            tenant_id=context.tenant.tenant_id,
            document_id=context.document_id,
            version_id=context.version_id,
            parser_requested=w.run.parser_requested,
            max_pages=w.service.max_pages,
        )
        w.raw = outcome.raw
        w.attempted = outcome.attempted
        w.selected_parser = outcome.selected_parser
        w.used_parser = outcome.used_parser
        w.fallbacks = [name for name in outcome.attempted if name != outcome.used_parser]
        for attempt in outcome.attempts:
            await w.service.ingestion_repo.add_parser_attempt(
                context.tenant,
                ParserAttemptRecord(
                    attempt_id=deterministic_id(
                        "parser_attempt",
                        str(context.tenant.tenant_id),
                        str(context.ingestion_run_id),
                        attempt.parser_name,
                    ),
                    tenant_id=context.tenant.tenant_id,
                    ingestion_run_id=context.ingestion_run_id,
                    parser_name=attempt.parser_name,
                    parser_version=attempt.parser_version,
                    success=attempt.success,
                    duration_ms=attempt.duration_ms,
                    failure_category=attempt.failure_category,
                    warnings=[],
                    metadata={
                        "error": attempt.error or "",
                        "element_count": attempt.element_count,
                        "selected_parser": w.selected_parser or "",
                    },
                ),
            )
        w.run.parser_used = w.used_parser
        w.run.latest_warning = (
            f"selected={w.selected_parser}; used={w.used_parser}; {outcome.routing_reason}"
        )
        w.run.updated_at = datetime.now(UTC)
        await w.service.ingestion_repo.update_run(context.tenant, w.run)
        await w.service._flush()
        w.audit.record_routing(
            RoutingReasonCode.PRIMARY_PARSER_SELECTED
            if not w.run.parser_requested or w.run.parser_requested in {"auto", None}
            else RoutingReasonCode.PARSER_OVERRIDE,
            message=(
                f"Selected parser: {w.selected_parser}; used parser: {w.used_parser}"
                f" ({outcome.routing_reason})"
            ),
            selected_tool=w.selected_parser,
            details={
                "attempted": w.attempted,
                "requested": w.run.parser_requested,
                "selected_parser": w.selected_parser,
                "used_parser": w.used_parser,
                "routing_reason": outcome.routing_reason,
            },
        )
        w.audit.document.primary_parser = w.used_parser
        w.audit.document.fallback_parsers = w.fallbacks
        self._record_parse_audit(w.raw, primary=w.used_parser)
        w.audit.stage_completed(
            "PARSE",
            status=StageRunStatus.COMPLETED,
            output_count=len(w.raw.elements),
            warning_count=len(w.raw.warnings or []),
        )
        await w.save_json(
            "parse_raw",
            {
                "raw": w.raw.model_dump(mode="json"),
                "selected_parser": w.selected_parser,
                "used_parser": w.used_parser,
                "attempted": w.attempted,
                "fallbacks": w.fallbacks,
                "routing_reason": outcome.routing_reason,
                "vision_failed": w.vision_failed,
                "vision_target_count": w.vision_target_count,
            },
        )
        await self._run_vision(context)
        return StageOutcome(
            status=StageOutcomeStatus.COMPLETED,
            pages_processed=w.raw.page_count,
            elements_processed=len(w.raw.elements),
        )

    def _record_parse_audit(self, raw: RawParserResult, *, primary: str | None) -> None:
        """Populate per-page/per-element audit detail for the parse report.

        RawElement has no stable element_id yet (normalization assigns it),
        so this only records what's known at parse time — page, type,
        detector, position. The already-wired vision-provenance stamping
        later in the pipeline updates these same records once vision
        enrichment runs, and NORMALIZE flips per-element status forward.
        """
        w = self.w
        assert w.audit is not None
        for order, element in enumerate(raw.elements):
            page_no = int(element.page_start)
            bbox = None
            if element.bounding_boxes:
                box = element.bounding_boxes[0]
                bbox = {
                    "x0": float(box.x0),
                    "y0": float(box.y0),
                    "x1": float(box.x1),
                    "y1": float(box.y1),
                }
            w.audit.element_detected(
                page_number=page_no,
                normalized_element_type=element.element_type.value,
                original_parser_element_type=str(
                    element.metadata.get("raw_type") or element.element_type.value
                ),
                detector=primary,
                parser_name=primary,
                reading_order=element.reading_order if element.reading_order else order,
                bbox=bbox,
                section_path=list(element.section_path),
                confidence_score=element.parser_confidence,
                confidence_source=("parser" if element.parser_confidence is not None else None),
            )
        for page in raw.pages or []:
            w.audit.ensure_page(int(page.page_number))
            w.audit.page_completed(
                int(page.page_number),
                page_parser=primary,
                has_native_text=not bool(page.is_scanned),
                ocr_required=bool(page.is_scanned),
            )

    def _reconcile_normalized_audit(self, normalized: NormalizedDocument) -> None:
        """Pair parse-time audit records to their normalized counterparts.

        Mirrors local_pipeline.py's matching: RawElement has no element_id at
        detection time, so pair best-effort by (page, element_type) in
        detection order. Without this, every audit record stays at
        reached_normalized=False and reconcile_content_loss() (run at
        document_completed) flags every single element as a content loss —
        which is misleading for documents that processed fine.
        """
        w = self.w
        assert w.audit is not None
        by_page_type: dict[tuple[int | None, str | None], list] = {}
        for element in normalized.elements:
            key = (element.page_start, element.element_type.value)
            by_page_type.setdefault(key, []).append(element)
        normalized_ids = {element.element_id for element in normalized.elements}
        for report in list(w.audit._elements):
            key = (report.page_number, report.normalized_element_type)
            bucket = by_page_type.get(key) or []
            if not bucket:
                continue
            matched = bucket.pop(0)
            w.audit.update_element(
                report,
                element_id=matched.element_id,
                section_path=list(matched.section_path or []),
                reached_normalized=True,
                status=ElementProcessingStatus.PROCESSED,
                processing_tool=(
                    report.processing_tool
                    if report.detector == "vision"
                    or (report.detector or "").endswith("+vision")
                    or (report.processing_tool or "").startswith("parser+vision")
                    or report.processing_tool == "vision_enrichment"
                    else "normalizer"
                ),
            )
        w.audit.mark_normalized(normalized_ids)

    async def _run_vision(self, context: StageContext) -> None:
        w = self.w
        assert (
            w.audit is not None and w.raw is not None and w.data is not None and w.run is not None
        )
        stored = await w.load_json("parse_raw")
        if stored and stored.get("vision_done"):
            w.vision_failed = int(stored.get("vision_failed") or 0)
            w.vision_target_count = int(stored.get("vision_target_count") or 0)
            return
        vision_needed = [
            target for target in collect_visual_targets(w.raw) if target.tool == "vision"
        ]
        w.vision_target_count = len(vision_needed)
        w.vision_failed = 0
        vision_name = resolve_model_label(w.service.chat_model)
        if w.service.chat_model is not None and (
            w.mime == "application/pdf" or w.filename.lower().endswith(".pdf")
        ):
            w.audit.stage_started("VISION_ENRICHMENT", tool="vision", model_name=vision_name)

            async def _heartbeat() -> None:
                w.run.updated_at = datetime.now(UTC)
                w.run.heartbeat_at = datetime.now(UTC)
                await w.service.ingestion_repo.update_run(context.tenant, w.run)
                await w.service._flush()

            (
                vision_elements,
                enriched_pages,
                w.vision_target_count,
                w.vision_failed,
            ) = await _vision_enrich_pages(
                w.service.chat_model,
                w.data,
                w.raw,
                max_pages=w.service.vision_max_pages,
                on_progress=_heartbeat,
            )
            if vision_elements:
                w.raw.elements.extend(vision_elements)
            _stamp_hybrid_vision_provenance(
                w.audit,
                enriched_pages=enriched_pages,
                vision_model=vision_name,
                layout_parser=w.used_parser or w.selected_parser or "unknown",
            )
            w.audit.stage_completed(
                "VISION_ENRICHMENT",
                status=StageRunStatus.COMPLETED_WITH_WARNINGS
                if w.vision_failed
                else StageRunStatus.COMPLETED,
                output_count=len(vision_elements or []),
                warning_count=w.vision_failed,
            )
        elif w.vision_target_count:
            w.vision_failed = w.vision_target_count
            w.raw.warnings.append("vision_skipped:no_chat_model")
        await w.save_json(
            "parse_raw",
            {
                "raw": w.raw.model_dump(mode="json"),
                "selected_parser": w.selected_parser,
                "used_parser": w.used_parser,
                "attempted": w.attempted,
                "fallbacks": w.fallbacks,
                "vision_failed": w.vision_failed,
                "vision_target_count": w.vision_target_count,
                "vision_done": True,
            },
        )

    async def stage_normalize(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        assert w.audit is not None and w.raw is not None and w.data is not None
        if w.normalized is not None:
            return StageOutcome(
                status=StageOutcomeStatus.COMPLETED,
                pages_processed=w.normalized.page_count,
                elements_processed=len(w.normalized.elements),
            )
        source = ParseSource(
            tenant_id=context.tenant.tenant_id,
            document_id=context.document_id,
            version_id=context.version_id,
            filename=w.filename,
            mime_type=w.version.mime_type or "application/octet-stream",
            content=w.data,
        )
        w.audit.stage_started("NORMALIZE", tool="normalize_parser_result")
        w.normalized = normalize_parser_result(w.raw, source)
        self._reconcile_normalized_audit(w.normalized)
        w.audit.stage_completed(
            "NORMALIZE", status=StageRunStatus.COMPLETED, output_count=len(w.normalized.elements)
        )
        await w.save_json("normalized", w.normalized.model_dump(mode="json"))
        return StageOutcome(
            status=StageOutcomeStatus.COMPLETED,
            pages_processed=w.normalized.page_count,
            elements_processed=len(w.normalized.elements),
        )

    async def stage_store_elements(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        if w.normalized is None:
            raise PermanentError(
                "NORMALIZE must complete before STORE_ELEMENTS", code="missing_normalized"
            )
        await w.save_json(
            "elements_index",
            {
                "element_ids": [str(item.element_id) for item in w.normalized.elements],
                "count": len(w.normalized.elements),
            },
        )
        return StageOutcome(
            status=StageOutcomeStatus.COMPLETED,
            elements_processed=len(w.normalized.elements),
        )

    async def stage_skip_assets(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        return StageOutcome(
            status=StageOutcomeStatus.SKIPPED, warning="assets stored with original object"
        )

    async def stage_skip_optional(self, context: StageContext) -> StageOutcome:
        _ = context
        return StageOutcome(
            status=StageOutcomeStatus.SKIPPED, warning="handled in parse/vision/chunk"
        )

    async def stage_skip_communities(self, context: StageContext) -> StageOutcome:
        _ = context
        return StageOutcome(
            status=StageOutcomeStatus.SKIPPED, warning="community summarization disabled"
        )

    async def stage_enrich_images(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        await self._run_vision(context)
        warning = f"vision_failed={w.vision_failed}" if w.vision_failed else None
        return StageOutcome(
            status=StageOutcomeStatus.COMPLETED_WITH_WARNINGS
            if warning
            else StageOutcomeStatus.COMPLETED,
            warning=warning,
            elements_processed=len(w.raw.elements) if w.raw else 0,
        )

    async def stage_chunk(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        assert w.audit is not None and w.normalized is not None
        if w.chunks:
            return StageOutcome(
                status=StageOutcomeStatus.COMPLETED, elements_processed=len(w.chunks)
            )
        if not w.raw or not w.raw.elements:
            raise PermanentError("No extractable content found in document", code="empty_parse")
        w.audit.stage_started("CHUNK", tool="HierarchicalMultimodalChunker")
        chunks = HierarchicalMultimodalChunker().chunk(w.normalized)
        all_chunks = list(chunks.all_chunks)
        doc_title = (
            (w.document.title or "").strip() if w.document is not None else ""
        ) or w.filename
        stamped: list[ChunkBase] = []
        for chunk in all_chunks:
            meta = dict(chunk.metadata)
            meta["document_name"] = doc_title
            stamped.append(chunk.model_copy(update={"metadata": meta}))
        w.chunks = stamped
        w.audit.mark_downstream(chunking=True)
        w.audit.stage_completed("CHUNK", output_count=len(w.chunks))
        await w.save_json("chunks", {"chunks": [item.model_dump(mode="json") for item in w.chunks]})
        return StageOutcome(status=StageOutcomeStatus.COMPLETED, elements_processed=len(w.chunks))

    async def stage_embed(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        assert w.audit is not None
        if w.embedded:
            return StageOutcome(
                status=StageOutcomeStatus.COMPLETED, elements_processed=len(w.embedded)
            )
        if not w.chunks:
            raise PermanentError("CHUNK must complete before EMBED", code="missing_chunks")
        embed_name = resolve_model_label(w.service.embedding_model)
        w.audit.stage_started("EMBED", tool=str(embed_name), model_name=str(embed_name))
        document = w.document
        embedded = await EmbedChunksService(w.service.embedding_model).embed(
            w.chunks,
            parser=w.raw.parser_name if w.raw else None,
            security_labels=list(document.security_labels) if document else None,
            department=document.department if document else None,
            country=document.country if document else None,
            business_unit=document.business_unit if document else None,
            classification=document.classification if document else None,
            required_clearance=document.required_clearance if document else None,
            allowed_groups=list(document.allowed_groups) if document else None,
        )
        if not embedded.records:
            raise PermanentError("No embeddings produced from document", code="empty_embeddings")
        w.embedded = list(embedded.records)
        w.audit.stage_completed("EMBED", output_count=len(w.embedded))
        await w.save_json(
            "embeddings", {"records": [item.model_dump(mode="json") for item in w.embedded]}
        )
        if embedded.skipped_empty:
            return StageOutcome(
                status=StageOutcomeStatus.COMPLETED_WITH_WARNINGS,
                elements_processed=len(w.embedded),
                warning=f"skipped {embedded.skipped_empty} empty chunk(s) with no text to embed",
            )
        return StageOutcome(status=StageOutcomeStatus.COMPLETED, elements_processed=len(w.embedded))

    async def stage_index_vector(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        assert w.audit is not None
        if not w.embedded:
            raise PermanentError(
                "EMBED must complete before INDEX_VECTOR", code="missing_embeddings"
            )
        w.audit.stage_started("INDEX_VECTOR", tool="vector_store")
        await w.service.vector_store.ensure_collection(
            vector_size=len(w.embedded[0].content_vector)
        )
        await w.service.vector_store.upsert(context.tenant, w.embedded)
        await w.service.chunk_store.upsert(context.tenant, w.chunks)
        await w.service.lexical_store.upsert(context.tenant, w.chunks)
        w.audit.mark_downstream(vector_index=True)
        w.audit.stage_completed("INDEX_VECTOR", output_count=len(w.embedded))
        await w.save_json("index_vector", {"count": len(w.embedded), "upserted": True})
        return StageOutcome(status=StageOutcomeStatus.COMPLETED, elements_processed=len(w.embedded))

    async def stage_extract_graph(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        stored = await w.load_json("graph")
        if stored:
            w.graph_counts = {
                str(key): int(value) for key, value in (stored.get("counts") or {}).items()
            }
            return StageOutcome(status=StageOutcomeStatus.COMPLETED)
        if w.service.graph_store is None or w.normalized is None:
            return StageOutcome(status=StageOutcomeStatus.SKIPPED, warning="graph store disabled")
        assert w.audit is not None
        w.audit.stage_started("INDEX_GRAPH", tool="graph_store")
        chunking_result = ChunkingResult(
            parents=[chunk for chunk in w.chunks if chunk.parent_chunk_id is None],
            children=[chunk for chunk in w.chunks if chunk.parent_chunk_id is not None],
        )
        try:
            if w.service.structured_extractor is not None and w.service.semantic_graph:
                parents = list(chunking_result.parents)[:30]
                children = [
                    child
                    for child in chunking_result.children
                    if child.chunk_type.value in {"multimodal_composite", "table"}
                ][:30]
                build_result = await BuildKnowledgeGraphService(
                    w.service.structured_extractor,
                    w.service.graph_store,
                ).build(
                    context.tenant,
                    w.normalized,
                    ChunkingResult(parents=parents, children=children),
                    persist=True,
                )
                w.graph_counts = dict(build_result.upsert_counts)
            else:
                projected = StructuralGraphBuilder().build(w.normalized, chunking_result)
                w.graph_counts = await w.service.graph_store.upsert_graph(context.tenant, projected)
        except Exception as graph_exc:
            logger.warning(
                "semantic_graph_build_failed",
                error=str(graph_exc),
                document_id=str(context.document_id),
            )
            if w.raw is not None:
                w.raw.warnings.append(f"semantic_graph_failed:{type(graph_exc).__name__}")
            projected = StructuralGraphBuilder().build(w.normalized, chunking_result)
            w.graph_counts = await w.service.graph_store.upsert_graph(context.tenant, projected)
        w.audit.mark_downstream(graph_index=True)
        await w.save_json("graph", {"counts": w.graph_counts, "upserted": True})
        return StageOutcome(status=StageOutcomeStatus.COMPLETED)

    async def stage_index_graph(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        stored = await self.w.load_json("graph")
        if stored and stored.get("upserted"):
            return StageOutcome(status=StageOutcomeStatus.COMPLETED)
        if self.w.service.graph_store is None:
            return StageOutcome(status=StageOutcomeStatus.SKIPPED, warning="graph store disabled")
        return await self.stage_extract_graph(context)

    async def stage_finalize(self, context: StageContext) -> StageOutcome:
        await self.ensure_loaded(context)
        w = self.w
        assert w.run is not None and w.audit is not None
        if w.normalized is None:
            raise PermanentError(
                "Cannot finalize without normalized document", code="missing_normalized"
            )
        used_parser = w.used_parser or (w.raw.parser_name if w.raw else "unknown")
        parser_quality_ok = used_parser in _STRUCTURED_PARSERS
        vision_complete = w.vision_failed == 0
        w.needs_review = not parser_quality_ok or not vision_complete
        if w.raw is not None:
            if w.needs_review:
                if not parser_quality_ok:
                    w.raw.warnings.append(
                        f"needs_review:used_{used_parser}_selected_{w.selected_parser}"
                    )
                if not vision_complete:
                    w.raw.warnings.append(
                        f"needs_review:vision_incomplete_{w.vision_failed}/{w.vision_target_count}"
                    )
            for warning in w.raw.warnings or []:
                w.audit.add_issue(severity="warning", message=str(warning), stage_name="PARSE")
        if w.needs_review:
            document_status = DocumentLifecycleStatus.PARTIAL
            warning = w.raw.warnings[0] if w.raw and w.raw.warnings else "partial"
            w.run.latest_warning = warning
        elif w.raw and w.raw.warnings:
            document_status = DocumentLifecycleStatus.READY
            w.run.latest_warning = w.raw.warnings[0]
        else:
            document_status = DocumentLifecycleStatus.READY
            w.run.latest_warning = None
        w.run.pages_processed = w.normalized.page_count
        w.run.elements_processed = len(w.normalized.elements)
        w.run.parser_used = used_parser
        w.run.error_code = None
        w.run.error_message = None
        w.run.updated_at = datetime.now(UTC)
        await w.service.ingestion_repo.update_run(context.tenant, w.run)
        await w.service._set_document_status(
            context.tenant,
            w.run.document_id,
            document_status,
            updated_at=w.run.updated_at,
            metadata_updates={
                "page_count": w.normalized.page_count,
                "selected_parser": w.selected_parser,
                "used_parser": used_parser,
                "needs_review": w.needs_review,
            },
        )
        snapshot = w.audit.document_completed(
            ingestion_status=(
                IngestionRunStatus.PARTIAL.value
                if w.needs_review
                else (
                    IngestionRunStatus.COMPLETED_WITH_WARNINGS.value
                    if w.run.latest_warning
                    else IngestionRunStatus.COMPLETED.value
                )
            ),
            primary_parser=used_parser,
            fallback_parsers=w.fallbacks,
            total_pages=w.normalized.page_count,
            total_normalized_elements=len(w.normalized.elements),
        )
        if w.service.parsing_audit_repo is not None:
            await w.service.parsing_audit_repo.save_snapshot(context.tenant, snapshot)
        await w.service._flush()
        if w.needs_review:
            return StageOutcome(
                status=StageOutcomeStatus.COMPLETED_WITH_WARNINGS,
                warning=w.run.latest_warning,
                pages_processed=w.normalized.page_count,
                elements_processed=len(w.normalized.elements),
            )
        return StageOutcome(
            status=StageOutcomeStatus.COMPLETED,
            warning=w.run.latest_warning,
            pages_processed=w.normalized.page_count,
            elements_processed=len(w.normalized.elements),
        )


async def persist_stage_progress(
    service: ProcessRegisteredDocumentService,
    tenant: TenantContext,
    run: Any,
    stages: list[Any],
    stage: IngestionStageName,
) -> None:
    _ = stage
    await service.ingestion_repo.update_run(tenant, run)
    for row in stages:
        await service.ingestion_repo.update_stage(tenant, row)
    await service._flush()


async def run_document_pipeline(
    service: ProcessRegisteredDocumentService,
    tenant: TenantContext,
    ingestion_run_id: UUID,
    *,
    worker_id: str | None = None,
    should_stop: Any | None = None,
    retry_policy: RetryPolicy | None = None,
    stream_message_id: str | None = None,
) -> OrchestrationResult:
    run = await service.ingestion_repo.get_run(tenant, ingestion_run_id)
    if run is None:
        raise NotFoundError(
            "Ingestion run not found", details={"ingestion_run_id": str(ingestion_run_id)}
        )
    stages = await service.ingestion_repo.list_stages(tenant, ingestion_run_id)
    workspace = PipelineWorkspace(service)
    workspace.tenant = tenant
    workspace.run = run
    pipeline = DocumentPipeline(workspace)
    settings = get_settings()
    policy = retry_policy or RetryPolicy(
        max_attempts=settings.worker.max_stage_attempts,
        base_delay_seconds=settings.worker.retry_base_delay_seconds,
        max_delay_seconds=settings.worker.retry_max_delay_seconds,
        jitter=settings.worker.retry_jitter,
    )

    async def on_stage(updated_run, updated_stages, stage_name) -> None:
        await persist_stage_progress(service, tenant, updated_run, updated_stages, stage_name)

    orchestrator = IngestionOrchestrator(
        pipeline.handlers(),
        retry_policy=policy,
        on_stage=on_stage,
        should_stop=should_stop,
        worker_id=worker_id,
    )
    now = datetime.now(UTC)
    run.status = IngestionRunStatus.RUNNING
    run.started_at = run.started_at or now
    run.worker_id = worker_id or run.worker_id
    run.heartbeat_at = now
    await service.ingestion_repo.update_run(tenant, run)
    await service._set_document_status(
        tenant,
        run.document_id,
        DocumentLifecycleStatus.INGESTING,
        updated_at=now,
    )
    await service._flush()

    with usage_context(
        tenant_id=tenant.tenant_id,
        document_id=run.document_id,
        ingestion_run_id=ingestion_run_id,
    ):
        try:
            result = await orchestrator.run(
                tenant=tenant,
                run=run,
                stage_records=stages,
                artifacts={"stream_message_id": stream_message_id} if stream_message_id else None,
            )
        except Exception as exc:
            failed = datetime.now(UTC)
            run.status = IngestionRunStatus.FAILED
            run.error_code = type(exc).__name__
            run.error_message = str(exc)
            run.updated_at = failed
            await service.ingestion_repo.update_run(tenant, run)
            await service._set_document_status(
                tenant,
                run.document_id,
                DocumentLifecycleStatus.FAILED,
                updated_at=failed,
            )
            await service._flush()
            logger.exception(
                "ingestion_pipeline_failed",
                ingestion_run_id=str(ingestion_run_id),
            )
            # The failure is already durably persisted above (run + document
            # status FAILED). Re-raising here would crash the whole worker
            # process for what is a per-run failure, taking every other
            # queued document down with it.
            return OrchestrationResult(
                run_status=IngestionRunStatus.FAILED,
                progress=IngestionProgress(
                    current_stage=None,
                    completed_stages=[],
                    pages_processed=0,
                    elements_processed=0,
                    estimated_completion_percent=0.0,
                    retry_count=0,
                ),
            )

    await persist_stage_progress(
        service,
        tenant,
        run,
        stages,
        result.failed_stage or IngestionStageName.FINALIZE,
    )
    if result.run_status is IngestionRunStatus.FAILED:
        await service._set_document_status(
            tenant,
            run.document_id,
            DocumentLifecycleStatus.FAILED,
            updated_at=datetime.now(UTC),
        )
        await service._flush()
    elif (
        result.run_status in SUCCESSFUL_RUN_STATUSES
        and result.run_status is IngestionRunStatus.PARTIAL
    ):
        await service._set_document_status(
            tenant,
            run.document_id,
            DocumentLifecycleStatus.PARTIAL,
            updated_at=datetime.now(UTC),
        )
        await service._flush()
    return result
