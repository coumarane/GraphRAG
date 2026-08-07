"""Local PDF → chunk → embed → index pipeline for API/dev runtimes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from enterprise_rag.application.chunking import EmbedChunksService, HierarchicalMultimodalChunker
from enterprise_rag.domain.chunks.protocols import ChunkVectorStore
from enterprise_rag.domain.chunks.vectors import ChunkingResult
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.graph.protocols import GraphStore
from enterprise_rag.domain.graph.structural import StructuralGraphBuilder
from enterprise_rag.domain.ingestion.protocols import DocumentRepository, IngestionRepository
from enterprise_rag.domain.ingestion.stages import (
    DocumentLifecycleStatus,
    IngestionRunStatus,
    StageStatus,
)
from enterprise_rag.domain.models.protocols import EmbeddingModel
from enterprise_rag.domain.parsing.normalize import normalize_parser_result
from enterprise_rag.domain.parsing.types import ParseSource, RawElement, RawPage, RawParserResult
from enterprise_rag.domain.retrieval.protocols import ChunkLookupStore, LexicalSearchStore
from enterprise_rag.domain.storage.protocols import ObjectStore
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import NotFoundError, ValidationError
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)


def _extract_pdf_raw(data: bytes, *, filename: str, max_pages: int) -> RawParserResult:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        page_count = len(document)
        limit = min(page_count, max_pages)
        elements: list[RawElement] = []
        pages: list[RawPage] = []
        order = 0
        for index in range(limit):
            page = document[index]
            text_page = page.get_textpage()
            try:
                text = (text_page.get_text_bounded() or "").strip()
            finally:
                text_page.close()
            page.close()
            pages.append(RawPage(page_number=index + 1, text_density=float(len(text))))
            if not text:
                continue
            blocks = [block.strip() for block in text.split("\n") if block.strip()] or [text]
            for block in blocks:
                elements.append(
                    RawElement(
                        element_type=ElementType.TEXT,
                        page_start=index + 1,
                        page_end=index + 1,
                        reading_order=order,
                        raw_content=block,
                        normalized_content=block,
                    )
                )
                order += 1
    finally:
        document.close()

    warnings: list[str] = []
    if page_count > limit:
        warnings.append(f"truncated_to_{limit}_of_{page_count}_pages")
    if not elements:
        raise ValidationError(
            "No extractable text found in PDF (may be scanned-only)",
            details={"filename": filename},
        )
    return RawParserResult(
        parser_name="pdfium_text",
        parser_version="local-1",
        title=filename,
        page_count=len(pages),
        pages=pages,
        elements=elements,
        warnings=warnings,
    )


def _extract_text_raw(data: bytes, *, filename: str) -> RawParserResult:
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValidationError("Empty text document", details={"filename": filename})
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()] or [text]
    elements = [
        RawElement(
            element_type=ElementType.TEXT,
            page_start=1,
            page_end=1,
            reading_order=index,
            raw_content=block,
            normalized_content=block,
        )
        for index, block in enumerate(blocks)
    ]
    return RawParserResult(
        parser_name="plaintext",
        parser_version="local-1",
        title=filename,
        page_count=1,
        pages=[RawPage(page_number=1, text_density=float(len(text)))],
        elements=elements,
        warnings=[],
    )


@dataclass
class ProcessRegisteredDocumentService:
    """Index a registered document in-process (no separate worker queue)."""

    document_repo: DocumentRepository
    ingestion_repo: IngestionRepository
    object_store: ObjectStore
    embedding_model: EmbeddingModel
    vector_store: ChunkVectorStore
    chunk_store: ChunkLookupStore
    lexical_store: LexicalSearchStore
    graph_store: GraphStore | None = None
    max_pages: int = 2_000

    async def execute(self, tenant: TenantContext, ingestion_run_id: UUID) -> None:
        run = await self.ingestion_repo.get_run(tenant, ingestion_run_id)
        if run is None:
            raise NotFoundError(
                "Ingestion run not found",
                details={"ingestion_run_id": str(ingestion_run_id)},
            )
        stages = await self.ingestion_repo.list_stages(tenant, ingestion_run_id)
        version = await self.document_repo.get_version(tenant, run.version_id)
        if version is None or not version.original_object_key:
            raise NotFoundError(
                "Document version or object key missing",
                details={"version_id": str(run.version_id)},
            )

        now = datetime.now(UTC)
        run.status = IngestionRunStatus.RUNNING
        run.updated_at = now
        await self.ingestion_repo.update_run(tenant, run)

        document = await self.document_repo.get_document(tenant, run.document_id)
        if document is not None:
            document.status = DocumentLifecycleStatus.INGESTING
            document.updated_at = now
            await self.document_repo.update_document(tenant, document)

        try:
            data = await self.object_store.get_bytes(
                tenant, object_key=version.original_object_key
            )
            filename = version.source_filename or Path(version.original_object_key).name
            mime = (version.mime_type or "").lower()
            if mime == "application/pdf" or filename.lower().endswith(".pdf"):
                raw = await asyncio.to_thread(
                    _extract_pdf_raw, data, filename=filename, max_pages=self.max_pages
                )
            elif mime.startswith("text/") or filename.lower().endswith(
                (".txt", ".md", ".markdown", ".csv")
            ):
                raw = _extract_text_raw(data, filename=filename)
            else:
                raise ValidationError(
                    "Local indexer supports PDF and plain text only",
                    details={"mime_type": mime, "filename": filename},
                )

            source = ParseSource(
                tenant_id=tenant.tenant_id,
                document_id=run.document_id,
                version_id=run.version_id,
                filename=filename,
                mime_type=version.mime_type or "application/octet-stream",
                content=data,
            )
            normalized = normalize_parser_result(raw, source)
            chunks = HierarchicalMultimodalChunker().chunk(normalized)
            all_chunks = list(chunks.all_chunks)
            embedded = await EmbedChunksService(self.embedding_model).embed(
                all_chunks, parser=raw.parser_name
            )
            if not embedded.records:
                raise ValidationError("No embeddings produced from document")

            await self.vector_store.ensure_collection(
                vector_size=len(embedded.records[0].content_vector)
            )
            await self.vector_store.upsert(tenant, embedded.records)
            await self.chunk_store.upsert(tenant, all_chunks)
            await self.lexical_store.upsert(tenant, all_chunks)

            graph_counts: dict[str, int] = {}
            if self.graph_store is not None:
                # Structural graph is deterministic (document → sections → chunks).
                # Semantic LLM extraction can be layered later without blocking chat.
                projected = StructuralGraphBuilder().build(
                    normalized,
                    ChunkingResult(
                        parents=[c for c in all_chunks if c.parent_chunk_id is None],
                        children=[c for c in all_chunks if c.parent_chunk_id is not None],
                    ),
                )
                graph_counts = await self.graph_store.upsert_graph(tenant, projected)

            done = datetime.now(UTC)
            for stage in stages:
                stage.status = StageStatus.COMPLETED
                stage.attempt_count = max(1, stage.attempt_count)
                stage.started_at = stage.started_at or done
                stage.completed_at = done
                stage.warning = None
                stage.error_code = None
                stage.error_message = None
                await self.ingestion_repo.update_stage(tenant, stage)

            run.status = (
                IngestionRunStatus.COMPLETED_WITH_WARNINGS
                if raw.warnings
                else IngestionRunStatus.COMPLETED
            )
            run.pages_processed = normalized.page_count
            run.elements_processed = len(normalized.elements)
            run.parser_used = raw.parser_name
            run.latest_warning = raw.warnings[0] if raw.warnings else None
            run.error_code = None
            run.error_message = None
            run.updated_at = done
            await self.ingestion_repo.update_run(tenant, run)

            if document is not None:
                document.status = DocumentLifecycleStatus.READY
                document.updated_at = done
                await self.document_repo.update_document(tenant, document)

            logger.info(
                "local_ingest_completed",
                ingestion_run_id=str(ingestion_run_id),
                document_id=str(run.document_id),
                chunks=len(embedded.records),
                pages=normalized.page_count,
                graph_nodes=graph_counts.get("nodes"),
                graph_relationships=graph_counts.get("relationships"),
            )
        except Exception as exc:
            failed = datetime.now(UTC)
            run.status = IngestionRunStatus.FAILED
            run.error_code = type(exc).__name__
            run.error_message = str(exc)
            run.updated_at = failed
            await self.ingestion_repo.update_run(tenant, run)
            if document is not None:
                document.status = DocumentLifecycleStatus.FAILED
                document.updated_at = failed
                await self.document_repo.update_document(tenant, document)
            logger.exception(
                "local_ingest_failed",
                ingestion_run_id=str(ingestion_run_id),
                document_id=str(run.document_id),
            )
            raise
