"""Convert chunks/hits into ``RetrievedEvidence`` and assemble bounded context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from enterprise_rag.domain.chunks.models import ChunkBase
from enterprise_rag.domain.chunks.vectors import VectorSearchHit
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.retrieval.fusion import deduplicate_evidence
from enterprise_rag.domain.retrieval.models import RetrievedEvidence


def chunk_to_evidence(
    chunk: ChunkBase,
    *,
    score: float | None = None,
    score_components: Mapping[str, float] | None = None,
    document_name: str | None = None,
) -> RetrievedEvidence:
    """Map a chunk into retrieval evidence."""
    name = document_name
    if name is None:
        meta_name = chunk.metadata.get("document_name")
        name = (
            meta_name
            if isinstance(meta_name, str) and meta_name
            else str(chunk.document_id)
        )
    return RetrievedEvidence(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        document_version_id=chunk.version_id,
        document_name=name,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        section_path=list(chunk.section_path),
        element_id=chunk.element_ids[0] if chunk.element_ids else None,
        modality=chunk.modality,
        source_object_key=chunk.source_object_keys[0] if chunk.source_object_keys else "",
        text=chunk.text,
        score=score,
        score_components=dict(score_components or {}),
    )


def hit_to_evidence(
    hit: VectorSearchHit,
    *,
    chunk: ChunkBase | None = None,
    document_name: str | None = None,
    score_component: str = "dense",
) -> RetrievedEvidence:
    """Map a vector hit (optionally hydrated) into evidence."""
    resolved = chunk or hit.chunk
    if resolved is not None:
        return chunk_to_evidence(
            resolved,
            score=hit.score,
            score_components={score_component: hit.score},
            document_name=document_name,
        )
    payload = hit.payload
    name = document_name or str(payload.document_id)
    return RetrievedEvidence(
        chunk_id=payload.chunk_id,
        document_id=payload.document_id,
        document_version_id=payload.version_id,
        document_name=name,
        page_start=payload.page_start,
        page_end=payload.page_end,
        section_path=list(payload.section_path),
        element_id=None,
        modality=payload.modality,
        source_object_key=payload.source_object_keys[0] if payload.source_object_keys else "",
        text=payload.text_preview,
        score=hit.score,
        score_components={score_component: hit.score},
    )


def assemble_context(
    evidence: Sequence[RetrievedEvidence],
    *,
    top_k: int,
    prefer_modality_diversity: bool = True,
) -> list[RetrievedEvidence]:
    """Bound context size while preferring modality diversity when requested."""
    deduped = deduplicate_evidence(evidence)
    if not prefer_modality_diversity or top_k <= 1:
        return deduped[:top_k]

    selected: list[RetrievedEvidence] = []
    seen_modalities: set[Modality] = set()
    deferred: list[RetrievedEvidence] = []
    for item in deduped:
        if item.modality not in seen_modalities:
            selected.append(item)
            seen_modalities.add(item.modality)
        else:
            deferred.append(item)
        if len(selected) >= top_k:
            return selected[:top_k]
    for item in deferred:
        if len(selected) >= top_k:
            break
        selected.append(item)
    return selected[:top_k]


def document_name_map(
    chunks: Sequence[ChunkBase],
    *,
    overrides: Mapping[UUID, str] | None = None,
) -> dict[UUID, str]:
    """Build document_id → display name from chunk metadata and overrides."""
    names: dict[UUID, str] = dict(overrides or {})
    for chunk in chunks:
        if chunk.document_id in names:
            continue
        meta_name = chunk.metadata.get("document_name")
        if isinstance(meta_name, str) and meta_name:
            names[chunk.document_id] = meta_name
    return names
