"""Deletion pipeline vocabulary."""

from __future__ import annotations

from enum import StrEnum


class DeletionStageName(StrEnum):
    """Ordered stages for document / version deletion."""

    MARK_DELETING = "MARK_DELETING"
    DELETE_VECTORS = "DELETE_VECTORS"
    DELETE_GRAPH = "DELETE_GRAPH"
    DELETE_OBJECTS = "DELETE_OBJECTS"
    ARCHIVE_POSTGRES = "ARCHIVE_POSTGRES"
    INVALIDATE_CACHE = "INVALIDATE_CACHE"
    FINALIZE = "FINALIZE"


class DeletionOperationStatus(StrEnum):
    """Lifecycle of an asynchronous deletion operation."""

    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ReindexScope(StrEnum):
    """What derived projections to rebuild."""

    FULL = "full"
    VECTORS = "vectors"
    GRAPH = "graph"
    DOCUMENT_INTELLIGENCE = "document_intelligence"


DELETION_STAGE_ORDER: tuple[DeletionStageName, ...] = tuple(DeletionStageName)
