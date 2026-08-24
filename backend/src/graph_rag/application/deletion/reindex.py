"""Reindex / rebuild derived projections for a document version."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.application.document_intelligence.models import DocumentIntelligenceIngestOptions
from graph_rag.application.ingestion.stage_pipeline import artifact_key
from graph_rag.domain.chunks.protocols import ChunkVectorStore
from graph_rag.domain.deletion.stages import ReindexScope
from graph_rag.domain.graph.protocols import GraphStore
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.protocols import DocumentRepository, IngestionRepository
from graph_rag.domain.ingestion.records import IngestionRunRecord
from graph_rag.domain.ingestion.stages import IngestionRunStatus, IngestionStageName
from graph_rag.domain.ingestion.state_machine import build_persisted_stage_records
from graph_rag.domain.storage.protocols import ObjectStore
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import NotFoundError, ValidationError
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)


class ReindexResult(BaseModel):
    """Accepted reindex / rebuild operation."""

    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    scope: ReindexScope
    ingestion_run_id: UUID | None = None
    vectors_cleared: int = 0
    graph_cleared: int = 0
    status: str = "accepted"
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ReindexDocumentService:
    """Clear selected derived indexes and enqueue a resumable ingestion run."""

    document_repo: DocumentRepository
    ingestion_repo: IngestionRepository
    vector_store: ChunkVectorStore | None = None
    graph_store: GraphStore | None = None
    object_store: ObjectStore | None = None
    config_fingerprint: str = "reindex-v1"

    async def execute(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        scope: ReindexScope = ReindexScope.FULL,
        chunk_ids: list[UUID] | None = None,
        document_intelligence: DocumentIntelligenceIngestOptions | None = None,
    ) -> ReindexResult:
        tenant.ensure_authorized()
        document = await self.document_repo.get_document(tenant, document_id)
        if document is None:
            raise NotFoundError(
                "Document not found",
                details={"document_id": str(document_id)},
            )
        if document.current_version_id is None:
            raise ValidationError(
                "Document has no current version to reindex",
                details={"document_id": str(document_id)},
            )
        if scope is ReindexScope.DOCUMENT_INTELLIGENCE and not (
            document_intelligence is not None and document_intelligence.enabled
        ):
            raise ValidationError(
                "document_intelligence options with enabled=true are required for this scope",
                details={"scope": scope.value},
            )
        version_id = document.current_version_id
        warnings: list[str] = []
        vectors_cleared = 0
        graph_cleared = 0

        if scope in {ReindexScope.FULL, ReindexScope.VECTORS, ReindexScope.DOCUMENT_INTELLIGENCE}:
            if self.vector_store is None:
                warnings.append("vector_store_not_configured")
            else:
                try:
                    vectors_cleared = await self.vector_store.delete_version(
                        tenant,
                        document_id=document_id,
                        version_id=version_id,
                    )
                except Exception as exc:  # noqa: BLE001 - best-effort clear
                    warnings.append(f"vector_clear_failed:{type(exc).__name__}")
                    logger.warning(
                        "reindex_vector_clear_failed",
                        document_id=str(document_id),
                        error=str(exc),
                    )

        if scope in {ReindexScope.FULL, ReindexScope.GRAPH, ReindexScope.DOCUMENT_INTELLIGENCE}:
            if self.graph_store is None:
                warnings.append("graph_store_not_configured")
            else:
                try:
                    graph_cleared = await self.graph_store.delete_version(
                        tenant,
                        document_id=document_id,
                        version_id=version_id,
                        chunk_ids=chunk_ids,
                    )
                except Exception as exc:  # noqa: BLE001 - best-effort clear
                    warnings.append(f"graph_clear_failed:{type(exc).__name__}")
                    logger.warning(
                        "reindex_graph_clear_failed",
                        document_id=str(document_id),
                        error=str(exc),
                    )

        if scope is ReindexScope.DOCUMENT_INTELLIGENCE:
            if self.object_store is None:
                warnings.append("object_store_not_configured")
            else:
                # Stage artifacts are cached by (tenant, document, version) only, not
                # run_id -- stage_chunk/stage_embed/stage_extract_graph each
                # short-circuit unconditionally when their cached artifact already
                # exists. Resuming at EXTRACT_DOCUMENT_INTELLIGENCE alone would leave
                # those stale, so newly-promoted fields/entity mappings would never
                # actually get attached. parse_raw/normalized are deliberately left
                # alone -- no reason to re-parse for a DI-only reprocess.
                for name in ("chunks", "embeddings", "graph"):
                    key = artifact_key(tenant.tenant_id, document_id, version_id, name)
                    await self.object_store.delete_prefix(tenant, prefix=key)

        if scope is ReindexScope.FULL:
            if self.object_store is None:
                warnings.append("object_store_not_configured")
            else:
                # FULL means from scratch: re-parse the stored original rather than
                # reusing whatever PARSE/NORMALIZE produced last time (parser fixes,
                # e.g. new bounding-box extraction, only apply to documents that
                # re-run PARSE -- a resume that starts later than PARSE would keep
                # serving the old cached elements forever). Clear every
                # (tenant, document, version)-keyed artifact downstream of it too,
                # since they're all stale once the source elements can change.
                for name in ("parse_raw", "normalized", "chunks", "embeddings", "graph"):
                    key = artifact_key(tenant.tenant_id, document_id, version_id, name)
                    await self.object_store.delete_prefix(tenant, prefix=key)

        resume_stage = _resume_stage_for_scope(scope)
        run_id = new_id()
        stages = build_persisted_stage_records(
            tenant_id=tenant.tenant_id,
            ingestion_run_id=run_id,
        )
        # Mark stages before resume_stage as skipped so orchestration can resume.
        from graph_rag.domain.ingestion.stages import StageStatus

        for stage in stages:
            if _stage_index(stage.stage) < _stage_index(resume_stage):
                stage.status = StageStatus.SKIPPED

        version = await self.document_repo.get_version(tenant, version_id)
        content_hash = version.content_hash if version is not None else "0" * 64
        run = await self.ingestion_repo.create_run(
            tenant,
            IngestionRunRecord(
                ingestion_run_id=run_id,
                tenant_id=tenant.tenant_id,
                document_id=document_id,
                version_id=version_id,
                status=IngestionRunStatus.PENDING,
                parser_requested="reindex",
                config_fingerprint=self.config_fingerprint,
                content_hash=content_hash or "0" * 64,
                metadata={
                    "reindex_scope": scope.value,
                    "resume_stage": resume_stage.value,
                    **(
                        {"document_intelligence": document_intelligence.model_dump(mode="json")}
                        if document_intelligence is not None
                        else {}
                    ),
                },
            ),
            stages,
        )
        result = ReindexResult(
            operation_id=new_id(),
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            scope=scope,
            ingestion_run_id=run.ingestion_run_id,
            vectors_cleared=vectors_cleared,
            graph_cleared=graph_cleared,
            warnings=warnings,
        )
        logger.info(
            "reindex_accepted",
            document_id=str(document_id),
            scope=scope.value,
            ingestion_run_id=str(run.ingestion_run_id),
        )
        return result


def _resume_stage_for_scope(scope: ReindexScope) -> IngestionStageName:
    if scope is ReindexScope.FULL:
        return IngestionStageName.PARSE
    if scope is ReindexScope.VECTORS:
        return IngestionStageName.EMBED
    if scope is ReindexScope.GRAPH:
        return IngestionStageName.EXTRACT_GRAPH
    # ReindexScope has exactly four members; DOCUMENT_INTELLIGENCE is the
    # only one left once FULL/VECTORS/GRAPH are ruled out.
    return IngestionStageName.EXTRACT_DOCUMENT_INTELLIGENCE


def _stage_index(stage: IngestionStageName) -> int:
    from graph_rag.domain.ingestion.stages import INGESTION_STAGE_ORDER

    return INGESTION_STAGE_ORDER.index(stage)


# Re-export helper for callers that only need delete+reindex pairing.
__all__ = ["ReindexDocumentService", "ReindexResult", "ReindexScope"]
