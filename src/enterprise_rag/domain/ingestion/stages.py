"""Ingestion stage vocabulary and ordered pipeline definition."""

from __future__ import annotations

from enum import StrEnum


class IngestionStageName(StrEnum):
    """Ordered resumable ingestion stages (specs/04)."""

    VALIDATE = "VALIDATE"
    HASH = "HASH"
    REGISTER_DOCUMENT = "REGISTER_DOCUMENT"
    STORE_ORIGINAL = "STORE_ORIGINAL"
    INSPECT = "INSPECT"
    SELECT_PARSER = "SELECT_PARSER"
    PARSE = "PARSE"
    NORMALIZE = "NORMALIZE"
    STORE_ELEMENTS = "STORE_ELEMENTS"
    EXTRACT_ASSETS = "EXTRACT_ASSETS"
    ENRICH_IMAGES = "ENRICH_IMAGES"
    ENRICH_TABLES = "ENRICH_TABLES"
    ENRICH_EQUATIONS = "ENRICH_EQUATIONS"
    BUILD_CONTEXT = "BUILD_CONTEXT"
    CHUNK = "CHUNK"
    EMBED = "EMBED"
    INDEX_VECTOR = "INDEX_VECTOR"
    EXTRACT_GRAPH = "EXTRACT_GRAPH"
    RESOLVE_ENTITIES = "RESOLVE_ENTITIES"
    INDEX_GRAPH = "INDEX_GRAPH"
    SUMMARIZE_COMMUNITIES = "SUMMARIZE_COMMUNITIES"
    FINALIZE = "FINALIZE"


class StageStatus(StrEnum):
    """Per-stage execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class DocumentLifecycleStatus(StrEnum):
    """Document / version lifecycle status."""

    REGISTERED = "registered"
    INGESTING = "ingesting"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class IngestionRunStatus(StrEnum):
    """Ingestion run lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


SUCCESSFUL_RUN_STATUSES: frozenset[IngestionRunStatus] = frozenset(
    {
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.COMPLETED_WITH_WARNINGS,
        IngestionRunStatus.PARTIAL,
    }
)


# Ordered pipeline used by the state machine.
INGESTION_STAGE_ORDER: tuple[IngestionStageName, ...] = tuple(IngestionStageName)

# Relative weights for progress estimation (do not promise ETA).
STAGE_WEIGHTS: dict[IngestionStageName, float] = {
    IngestionStageName.VALIDATE: 1,
    IngestionStageName.HASH: 1,
    IngestionStageName.REGISTER_DOCUMENT: 1,
    IngestionStageName.STORE_ORIGINAL: 2,
    IngestionStageName.INSPECT: 3,
    IngestionStageName.SELECT_PARSER: 1,
    IngestionStageName.PARSE: 12,
    IngestionStageName.NORMALIZE: 4,
    IngestionStageName.STORE_ELEMENTS: 3,
    IngestionStageName.EXTRACT_ASSETS: 4,
    IngestionStageName.ENRICH_IMAGES: 8,
    IngestionStageName.ENRICH_TABLES: 6,
    IngestionStageName.ENRICH_EQUATIONS: 4,
    IngestionStageName.BUILD_CONTEXT: 2,
    IngestionStageName.CHUNK: 4,
    IngestionStageName.EMBED: 6,
    IngestionStageName.INDEX_VECTOR: 4,
    IngestionStageName.EXTRACT_GRAPH: 8,
    IngestionStageName.RESOLVE_ENTITIES: 4,
    IngestionStageName.INDEX_GRAPH: 4,
    IngestionStageName.SUMMARIZE_COMMUNITIES: 3,
    IngestionStageName.FINALIZE: 1,
}

TERMINAL_STAGE_STATUSES: frozenset[StageStatus] = frozenset(
    {
        StageStatus.COMPLETED,
        StageStatus.COMPLETED_WITH_WARNINGS,
        StageStatus.FAILED,
        StageStatus.SKIPPED,
        StageStatus.CANCELLED,
    }
)

SUCCESSFUL_STAGE_STATUSES: frozenset[StageStatus] = frozenset(
    {
        StageStatus.COMPLETED,
        StageStatus.COMPLETED_WITH_WARNINGS,
        StageStatus.SKIPPED,
    }
)
