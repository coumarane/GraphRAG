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
    prefer_tables: bool = False,
    prefer_charts: bool = False,
) -> list[RetrievedEvidence]:
    """Bound context size while preferring modality diversity when requested."""
    deduped = deduplicate_evidence(evidence)
    if top_k <= 0:
        return []
    if prefer_tables:
        table_like = [
            item
            for item in deduped
            if item.modality is Modality.TABLE
            or any(
                hint in (item.text or "").casefold()
                for hint in ("ppm", "n.d", "heavy metal", "impurit", "assay")
            )
        ]
        reserved = max(1, min(len(table_like), (top_k + 1) // 2))
        selected: list[RetrievedEvidence] = []
        seen: set[UUID] = set()
        for item in table_like:
            if len(selected) >= reserved:
                break
            selected.append(item)
            seen.add(item.chunk_id)
        for item in deduped:
            if len(selected) >= top_k:
                break
            if item.chunk_id in seen:
                continue
            selected.append(item)
            seen.add(item.chunk_id)
        return selected[:top_k]

    if prefer_charts:
        chart_like = [
            item
            for item in deduped
            if item.modality in {Modality.CHART, Modality.IMAGE, Modality.COMPOSITE}
            or any(
                hint in (item.text or "").casefold()
                for hint in (
                    "soft-focus",
                    "soft focus",
                    "byk-mac",
                    "angle of measurement",
                    "tone-up",
                    "synthetic mica (matte",
                    "synthetic mica (gloss",
                )
            )
        ]
        reserved = max(1, min(len(chart_like), (top_k + 1) // 2))
        selected: list[RetrievedEvidence] = []
        seen: set[UUID] = set()
        for item in chart_like:
            if len(selected) >= reserved:
                break
            selected.append(item)
            seen.add(item.chunk_id)
        for item in deduped:
            if len(selected) >= top_k:
                break
            if item.chunk_id in seen:
                continue
            selected.append(item)
            seen.add(item.chunk_id)
        return selected[:top_k]

    if not prefer_modality_diversity or top_k <= 1:
        return deduped[:top_k]

    selected = []
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


def ensure_document_coverage(
    selected: Sequence[RetrievedEvidence],
    pool: Sequence[RetrievedEvidence],
    *,
    document_ids: Sequence[UUID],
    top_k: int,
    min_per_doc: int = 1,
) -> list[RetrievedEvidence]:
    """Reserve evidence slots so multi-doc filters are not drowned by one large corpus."""
    if top_k <= 0:
        return []
    if len(document_ids) < 2:
        return list(selected)[:top_k]

    by_doc: dict[UUID, list[RetrievedEvidence]] = {doc_id: [] for doc_id in document_ids}
    for item in [*selected, *pool]:
        bucket = by_doc.get(item.document_id)
        if bucket is None:
            continue
        if any(existing.chunk_id == item.chunk_id for existing in bucket):
            continue
        bucket.append(item)

    reserved: list[RetrievedEvidence] = []
    used: set[UUID] = set()
    for doc_id in document_ids:
        for item in by_doc.get(doc_id, [])[: max(1, min_per_doc)]:
            if item.chunk_id in used:
                continue
            reserved.append(item)
            used.add(item.chunk_id)

    remainder: list[RetrievedEvidence] = []
    for item in selected:
        if item.chunk_id in used:
            continue
        remainder.append(item)
        used.add(item.chunk_id)

    return (reserved + remainder)[:top_k]


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
