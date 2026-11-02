"""Four-page evidence floor case. Scores are assigned. No live model is called."""

from __future__ import annotations

import pytest

from graph_rag.domain.chunks.models import ChunkBase, ChunkType
from graph_rag.domain.generation.grounding_policy import (
    EVIDENCE_SCORE_FLOOR,
    at_or_above_evidence_floor,
)
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.retrieval.assembly import chunk_to_evidence
from graph_rag.domain.retrieval.expansion import expand_parents_and_neighbors


def _chunk(
    *,
    tenant_id,
    document_id,
    version_id,
    text: str,
    page_start: int,
    page_end: int,
    parent_chunk_id=None,
) -> ChunkBase:
    return ChunkBase(
        chunk_id=new_id(),
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        parent_chunk_id=parent_chunk_id,
        modality=Modality.TEXT,
        chunk_type=ChunkType.SECTION if parent_chunk_id is None else ChunkType.TEXT,
        text=text,
        token_count=max(1, len(text.split())),
        page_start=page_start,
        page_end=page_end,
        section_path=["Body"],
        source_object_keys=["tenant/doc/four-page.pdf"],
        content_hash=content_sha256_hex(text),
    )


@pytest.mark.evaluation
def test_four_page_case_keeps_only_assigned_scores_at_or_above_the_floor() -> None:
    # Scores are assigned here. This case does not call a model, including
    # when RUN_LIVE_OPENAI_TESTS is unset.
    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    parent = _chunk(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="Pages one through four of the citrine serum note.",
        page_start=1,
        page_end=4,
    )
    pages = {
        1: ("Page one introduces the citrine serum base.", 0.05),
        2: ("Page two cites ceramide at two percent.", 0.42),
        3: ("Page three records the twelve week stability claim.", 0.04),
        4: ("Page four states the usage is twice daily.", 0.11),
    }
    children = {
        page: _chunk(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            text=text,
            page_start=page,
            page_end=page,
            parent_chunk_id=parent.chunk_id,
        )
        for page, (text, _score) in pages.items()
    }
    assigned = [
        chunk_to_evidence(children[page], score=score, score_components={"dense": score})
        for page, (_text, score) in pages.items()
    ]
    kept = [item for item in assigned if at_or_above_evidence_floor(item)]
    assert EVIDENCE_SCORE_FLOOR == 0.12
    assert [item.page_start for item in kept] == [2]
    expanded = expand_parents_and_neighbors(
        kept,
        {chunk.chunk_id: chunk for chunk in [parent, *children.values()]},
    )
    by_page = {(item.page_start, item.page_end): item.text for item in expanded}
    assert (2, 2) in by_page
    assert (1, 4) in by_page
    assert (4, 4) not in by_page
