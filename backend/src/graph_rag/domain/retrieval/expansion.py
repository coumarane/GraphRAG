"""Parent chunk and neighboring-element expansion for retrieved evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from graph_rag.domain.chunks.models import ChunkBase
from graph_rag.domain.retrieval.assembly import chunk_to_evidence
from graph_rag.domain.retrieval.models import RetrievedEvidence


def expand_parents_and_neighbors(
    seed: Sequence[RetrievedEvidence],
    chunks_by_id: Mapping[UUID, ChunkBase],
    *,
    include_parents: bool = True,
    include_neighbors: bool = True,
    document_names: Mapping[UUID, str] | None = None,
) -> list[RetrievedEvidence]:
    """Expand child hits with parent chunks and same-parent siblings.

    Neighbor expansion uses sibling children that share ``parent_chunk_id`` and
    adjacent page windows when parent linkage is absent.
    """
    expanded: list[RetrievedEvidence] = list(seed)
    seen: set[UUID] = {item.chunk_id for item in seed}
    names = document_names or {}

    for item in seed:
        chunk = chunks_by_id.get(item.chunk_id)
        if chunk is None:
            continue

        if include_parents and chunk.parent_chunk_id is not None:
            parent = chunks_by_id.get(chunk.parent_chunk_id)
            if parent is not None and parent.chunk_id not in seen:
                expanded.append(
                    chunk_to_evidence(
                        parent,
                        score=item.score,
                        score_components={"expansion": 1.0, "parent": 1.0},
                        document_name=names.get(parent.document_id),
                    )
                )
                seen.add(parent.chunk_id)

        if include_neighbors:
            for neighbor in _neighbor_chunks(chunk, chunks_by_id):
                if neighbor.chunk_id in seen:
                    continue
                expanded.append(
                    chunk_to_evidence(
                        neighbor,
                        score=(item.score or 0.0) * 0.5 if item.score is not None else None,
                        score_components={"neighbor_expansion": 1.0},
                        document_name=names.get(neighbor.document_id),
                    )
                )
                seen.add(neighbor.chunk_id)

    return expanded


def _neighbor_chunks(
    chunk: ChunkBase,
    chunks_by_id: Mapping[UUID, ChunkBase],
) -> list[ChunkBase]:
    siblings: list[ChunkBase] = []
    if chunk.parent_chunk_id is not None:
        for candidate in chunks_by_id.values():
            if (
                candidate.parent_chunk_id == chunk.parent_chunk_id
                and candidate.chunk_id != chunk.chunk_id
                and candidate.document_id == chunk.document_id
            ):
                siblings.append(candidate)
        siblings.sort(key=lambda item: (item.page_start, item.page_end, str(item.chunk_id)))
        # Keep immediate page-adjacent siblings only.
        return [
            sibling
            for sibling in siblings
            if abs(sibling.page_start - chunk.page_start) <= 1
        ][:4]

    # Fallback: same document, overlapping/adjacent pages.
    for candidate in chunks_by_id.values():
        if candidate.chunk_id == chunk.chunk_id:
            continue
        if candidate.document_id != chunk.document_id:
            continue
        if abs(candidate.page_start - chunk.page_start) <= 1:
            siblings.append(candidate)
    siblings.sort(key=lambda item: (item.page_start, str(item.chunk_id)))
    return siblings[:4]
