"""Document deletion and reindexing domain helpers."""

from graph_rag.domain.deletion.orphan import (
    collect_version_scoped_node_ids,
    is_shared_semantic_label,
    orphan_shared_entity_ids,
    related_shared_entity_ids,
)
from graph_rag.domain.deletion.protocols import CacheInvalidator
from graph_rag.domain.deletion.stages import (
    DELETION_STAGE_ORDER,
    DeletionOperationStatus,
    DeletionStageName,
    ReindexScope,
)

__all__ = [
    "DELETION_STAGE_ORDER",
    "CacheInvalidator",
    "DeletionOperationStatus",
    "DeletionStageName",
    "ReindexScope",
    "collect_version_scoped_node_ids",
    "is_shared_semantic_label",
    "orphan_shared_entity_ids",
    "related_shared_entity_ids",
]
