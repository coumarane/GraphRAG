"""Parent, child, and neighbor citations keep the stored page range."""

from __future__ import annotations

from graph_rag.domain.chunks.models import ChunkBase, ChunkType
from graph_rag.domain.citations.registry import evidence_to_citation
from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.retrieval.assembly import chunk_to_evidence
from graph_rag.domain.retrieval.expansion import expand_parents_and_neighbors
from graph_rag.domain.tenant import TenantContext


def _chunk(
    *,
    tenant_id,
    document_id,
    version_id,
    text: str,
    page_start: int,
    page_end: int,
    parent_chunk_id=None,
    chunk_id=None,
) -> ChunkBase:
    return ChunkBase(
        chunk_id=chunk_id or new_id(),
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
        source_object_keys=["tenant/doc/original.pdf"],
        content_hash=content_sha256_hex(text),
    )


def test_parent_child_and_neighbor_pages_stay_with_their_text() -> None:
    tenant = TenantContext(tenant_id=new_id())
    document_id = new_id()
    version_id = new_id()
    parent = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text=(
            "PageOneNiacinamideAnchor PageTwoCeramideAnchor "
            "PageThreeClaimAnchor PageFourUsageAnchor"
        ),
        page_start=1,
        page_end=4,
    )
    child = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="PageTwoCeramideAnchor",
        page_start=2,
        page_end=2,
        parent_chunk_id=parent.chunk_id,
    )
    neighbor = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="PageThreeClaimAnchor",
        page_start=3,
        page_end=3,
        parent_chunk_id=parent.chunk_id,
    )
    page_four = _chunk(
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        text="PageFourUsageAnchor",
        page_start=4,
        page_end=4,
        parent_chunk_id=parent.chunk_id,
    )
    chunks = {
        parent.chunk_id: parent,
        child.chunk_id: child,
        neighbor.chunk_id: neighbor,
        page_four.chunk_id: page_four,
    }
    seed = chunk_to_evidence(child, score=0.4, document_name="serum.pdf")
    expanded = expand_parents_and_neighbors(seed=[seed], chunks_by_id=chunks)
    by_id = {item.chunk_id: item for item in expanded}
    assert child.chunk_id in by_id
    assert parent.chunk_id in by_id
    assert by_id[child.chunk_id].page_start == 2
    assert by_id[child.chunk_id].page_end == 2
    assert by_id[parent.chunk_id].page_start == 1
    assert by_id[parent.chunk_id].page_end == 4
    assert by_id[neighbor.chunk_id].page_start == 3
    assert by_id[neighbor.chunk_id].page_end == 3

    for item in (by_id[child.chunk_id], by_id[parent.chunk_id], by_id[neighbor.chunk_id]):
        citation = evidence_to_citation(item, tenant=tenant, citation_id="C1")
        assert citation.document_id == item.document_id
        assert citation.page_start == item.page_start
        assert citation.page_end == item.page_end
        assert citation.evidence
    parent_citation = evidence_to_citation(
        by_id[parent.chunk_id], tenant=tenant, citation_id="C-parent"
    )
    assert "PageTwoCeramideAnchor" in parent_citation.evidence
    assert parent_citation.page_end != parent_citation.page_start
    four = evidence_to_citation(
        chunk_to_evidence(page_four, score=0.5, document_name="serum.pdf"),
        tenant=tenant,
        citation_id="C4",
    )
    assert four.page_start == 4
    assert four.page_end == 4
    assert "PageFourUsageAnchor" in four.evidence
