"""Production-safe heuristic reranker (no external rerank API required)."""

from __future__ import annotations

import re

from graph_rag.domain.models.contracts import (
    ModelCallMetadata,
    ModelRole,
    RerankRequest,
    RerankResponse,
    RerankResult,
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_/]{1,}", re.IGNORECASE)

_ASSAY_QUERY_HINTS = (
    "heavy metal",
    "impurit",
    "ppm",
    "assay",
    "specification",
    "composition",
    "content",
    "pb",
    "cd",
    "as",
    "hg",
    "lead",
    "cadmium",
    "arsenic",
    "mercury",
)

_ASSAY_DOC_HINTS = (
    "heavy metal",
    "impurit",
    "ppm",
    "n.d.",
    "not detected",
    "pb ",
    "cd ",
    "as ",
    "hg ",
    "assay",
    "mg/kg",
    "silkyflake",
    "ta glass",
    "ta-glass",
)


def _tokens(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_RE.finditer(text)}


class HeuristicReranker:
    """Lexical overlap + assay/table-aware boosts for grounded retrieval."""

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        query = request.query.casefold()
        query_tokens = _tokens(request.query)
        assay_query = any(hint in query for hint in _ASSAY_QUERY_HINTS)
        scored: list[tuple[int, str, float]] = []
        for index, item in enumerate(request.items):
            text = item.text.casefold()
            item_tokens = _tokens(item.text)
            overlap = len(query_tokens & item_tokens)
            score = float(overlap) + (0.01 * (len(request.items) - index))
            if assay_query:
                assay_hits = sum(1 for hint in _ASSAY_DOC_HINTS if hint in text)
                score += 1.5 * assay_hits
                if "n.d" in text or "ppm" in text:
                    score += 2.0
                if "|" in item.text or "\t" in item.text:
                    score += 1.0
                # Prefer impurity tables over coating marketing slides.
                if any(
                    coating in text
                    for coating in ("fe2o3", "fe3o4", "coated series", "interference")
                ) and not any(hint in text for hint in ("ppm", "n.d", "heavy metal content")):
                    score -= 1.5
            modality = str(item.metadata.get("modality") or "").casefold()
            if assay_query and modality == "table":
                score += 2.5
            scored.append((index, item.id, score))
        scored.sort(key=lambda row: row[2], reverse=True)
        top_n = request.top_n or len(scored)
        results = [
            RerankResult(id=item_id, score=score, index=index)
            for index, item_id, score in scored[:top_n]
        ]
        return RerankResponse(
            results=results,
            call=ModelCallMetadata(
                provider="heuristic",
                model_name=request.model_name or "heuristic-rerank-v1",
                role=ModelRole.RERANK,
            ),
        )
