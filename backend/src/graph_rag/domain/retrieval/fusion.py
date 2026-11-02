"""Score normalization, reciprocal-rank fusion and evidence deduplication."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from graph_rag.domain.retrieval.models import RetrievedEvidence


def normalize_scores(scores: Sequence[float]) -> list[float]:
    """Min-max normalize scores into ``[0, 1]`` (empty / constant → zeros/ones)."""
    if not scores:
        return []
    low = min(scores)
    high = max(scores)
    if high <= low:
        return [1.0 for _ in scores]
    span = high - low
    return [(value - low) / span for value in scores]


def _is_rank_component(key: str) -> bool:
    return key == "rrf" or key.startswith("rrf_list_")


def _original_retriever_scores(item: RetrievedEvidence) -> list[float]:
    """Retriever scores used for the evidence floor.

    A previous fusion stores those scores on ``source_score_*`` and puts the
    rank contribution on ``score``. Reading ``score`` again would treat the
    rank contribution as a retriever score.
    """
    sourced = [
        float(value)
        for key, value in item.score_components.items()
        if key.startswith("source_score_")
    ]
    if sourced:
        return sourced
    if item.score is None:
        return []
    return [float(item.score)]


def _remember_scores(bucket: list[float], scores: list[float]) -> None:
    for score in scores:
        if any(abs(score - seen) <= 1e-12 for seen in bucket):
            continue
        bucket.append(score)


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[RetrievedEvidence]],
    *,
    k: int = 60,
) -> list[RetrievedEvidence]:
    """Fuse ranked evidence lists with explainable RRF scores.

    ``score``, ``rrf``, and ``rrf_list_*`` are ranking scores. ``source_score_*``
    stays the original retriever score at every fusion level.
    """
    fused: dict[UUID, RetrievedEvidence] = {}
    rrf_scores: dict[UUID, float] = {}
    rank_components: dict[UUID, dict[str, float]] = {}
    trace_components: dict[UUID, dict[str, float]] = {}
    qualification: dict[UUID, list[float]] = {}

    for list_index, ranked in enumerate(ranked_lists):
        for rank, item in enumerate(ranked, start=1):
            contribution = 1.0 / (k + rank)
            chunk_id = item.chunk_id
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + contribution
            rank_components.setdefault(chunk_id, {})[f"rrf_list_{list_index}"] = contribution
            _remember_scores(
                qualification.setdefault(chunk_id, []),
                _original_retriever_scores(item),
            )
            traces = trace_components.setdefault(chunk_id, {})
            for key, value in item.score_components.items():
                if key.startswith("source_score_") or _is_rank_component(key):
                    continue
                traces[f"list{list_index}_{key}"] = float(value)
            existing = fused.get(chunk_id)
            if existing is None or (item.score or 0.0) > (existing.score or 0.0):
                fused[chunk_id] = item

    ordered_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)
    results: list[RetrievedEvidence] = []
    for chunk_id in ordered_ids:
        item = fused[chunk_id]
        components = {
            key: float(value)
            for key, value in item.score_components.items()
            if not key.startswith("source_score_") and not _is_rank_component(key)
        }
        components.update(trace_components.get(chunk_id, {}))
        components.update(rank_components.get(chunk_id, {}))
        for index, score in enumerate(qualification.get(chunk_id, [])):
            components[f"source_score_{index}"] = score
        components["rrf"] = rrf_scores[chunk_id]
        results.append(
            item.model_copy(
                update={
                    "score": rrf_scores[chunk_id],
                    "score_components": components,
                }
            )
        )
    return results


def deduplicate_evidence(
    evidence: Iterable[RetrievedEvidence],
    *,
    max_items: int | None = None,
) -> list[RetrievedEvidence]:
    """Drop duplicate chunk IDs and near-identical text, preserving order."""
    seen_ids: set[UUID] = set()
    seen_text: set[str] = set()
    unique: list[RetrievedEvidence] = []
    for item in evidence:
        if item.chunk_id in seen_ids:
            continue
        text_key = " ".join(item.text.casefold().split())
        if text_key and text_key in seen_text:
            continue
        seen_ids.add(item.chunk_id)
        if text_key:
            seen_text.add(text_key)
        unique.append(item)
        if max_items is not None and len(unique) >= max_items:
            break
    return unique


def apply_normalized_component(
    evidence: Sequence[RetrievedEvidence],
    *,
    component_name: str,
) -> list[RetrievedEvidence]:
    """Attach a min-max normalized view of the primary score."""
    scores = [item.score if item.score is not None else 0.0 for item in evidence]
    normalized = normalize_scores(scores)
    updated: list[RetrievedEvidence] = []
    for item, norm in zip(evidence, normalized, strict=True):
        components = dict(item.score_components)
        components[component_name] = norm
        updated.append(item.model_copy(update={"score_components": components}))
    return updated
