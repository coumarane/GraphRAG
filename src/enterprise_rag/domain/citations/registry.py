"""Build stable citation IDs from retrieved evidence."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from enterprise_rag.domain.citations.models import Citation
from enterprise_rag.domain.retrieval.models import RetrievedEvidence
from enterprise_rag.domain.tenant import TenantContext


class CitationRegistry:
    """Assigns ``C1..Cn`` identifiers for evidence items in context.

    The language model may only cite IDs present in this registry.
    """

    def __init__(
        self,
        tenant: TenantContext,
        evidence: Sequence[RetrievedEvidence],
    ) -> None:
        self._tenant = tenant
        self._by_id: dict[str, Citation] = {}
        self._by_chunk: dict[UUID, str] = {}
        for index, item in enumerate(evidence, start=1):
            citation_id = f"C{index}"
            citation = evidence_to_citation(
                item,
                tenant=tenant,
                citation_id=citation_id,
            )
            self._by_id[citation_id] = citation
            self._by_chunk[item.chunk_id] = citation_id

    @property
    def tenant(self) -> TenantContext:
        return self._tenant

    def all(self) -> list[Citation]:
        return list(self._by_id.values())

    def ids(self) -> list[str]:
        return list(self._by_id.keys())

    def get(self, citation_id: str) -> Citation | None:
        return self._by_id.get(citation_id)

    def contains(self, citation_id: str) -> bool:
        return citation_id in self._by_id

    def citation_id_for_chunk(self, chunk_id: UUID) -> str | None:
        return self._by_chunk.get(chunk_id)

    def select(self, citation_ids: Sequence[str]) -> list[Citation]:
        selected: list[Citation] = []
        seen: set[str] = set()
        for citation_id in citation_ids:
            if citation_id in seen:
                continue
            citation = self._by_id.get(citation_id)
            if citation is None:
                continue
            seen.add(citation_id)
            selected.append(citation)
        return selected

    def prompt_block(self) -> str:
        """Render evidence with citation IDs for the answer model."""
        lines: list[str] = []
        for citation in self._by_id.values():
            section = " > ".join(citation.section_path) if citation.section_path else ""
            lines.append(
                f"[{citation.citation_id}] doc={citation.document_name} "
                f"pages={citation.page_start}-{citation.page_end} "
                f"modality={citation.modality.value}"
                + (f" section={section}" if section else "")
                + f"\n{citation.evidence}"
            )
        return "\n\n".join(lines)


def evidence_to_citation(
    item: RetrievedEvidence,
    *,
    tenant: TenantContext,
    citation_id: str,
) -> Citation:
    """Convert retrieved evidence into a domain citation."""
    source_key = item.source_object_key.strip() or "unspecified"
    evidence_text = item.text.strip() or "(empty evidence)"
    page_start = item.page_start
    page_end = item.page_end
    # Prefer a precise landing page when legacy multi-page text chunks remain.
    if page_end - page_start >= 3:
        page_end = page_start
    return Citation(
        citation_id=citation_id,
        tenant_id=tenant.tenant_id,
        document_id=item.document_id,
        document_version_id=item.document_version_id,
        document_name=item.document_name or str(item.document_id),
        page_start=page_start,
        page_end=page_end,
        section_path=list(item.section_path),
        element_id=item.element_id,
        chunk_id=item.chunk_id,
        modality=item.modality,
        source_object_key=source_key,
        evidence=evidence_text[:4000],
    )
