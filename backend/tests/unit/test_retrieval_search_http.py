"""HTTP search must survive async quota settlement.

Production wires ``PostgresQuotaService``, whose ``reserve``, ``commit``, and
``release`` are coroutines. The search route used to call them like the
in-memory service. ``reservation`` was then a coroutine, and
``reservation.reservation_id`` raised::

    AttributeError: 'coroutine' object has no attribute 'reservation_id'

That happened after retrieval had already succeeded, for both an empty
evidence list and a multi-item list, and the API returned HTTP 500.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from graph_rag.api.app import create_app
from graph_rag.application.quotas.service import InMemoryQuotaService
from graph_rag.application.retrieval.retrieve import RetrieveEvidenceResult
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.chunks.models import ChunkType
from graph_rag.domain.chunks.vectors import (
    ChunkVectorPayload,
    ChunkVectorRecord,
    VectorSearchRequest,
)
from graph_rag.domain.ids import content_sha256_hex, deterministic_id, new_id
from graph_rag.domain.modality import Modality
from graph_rag.domain.retrieval.intent import analyze_query
from graph_rag.domain.retrieval.models import RetrievalResult, RetrievedEvidence
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore


class _AsyncQuota:
    """Postgres-shaped quota service: every settlement method is async."""

    def __init__(self, inner: InMemoryQuotaService) -> None:
        self._inner = inner
        self.reserve_calls = 0
        self.commit_calls = 0
        self.release_calls = 0

    def ensure_default_plan(self) -> None:
        self._inner.ensure_default_plan()

    def assign_default(self, **kwargs: object) -> None:
        self._inner.assign_default(**kwargs)  # type: ignore[arg-type]

    async def reserve(self, **kwargs: object):
        self.reserve_calls += 1
        return self._inner.reserve(**kwargs)  # type: ignore[arg-type]

    async def commit(self, **kwargs: object) -> None:
        self.commit_calls += 1
        self._inner.commit(**kwargs)  # type: ignore[arg-type]

    async def release(self, **kwargs: object) -> None:
        self.release_calls += 1
        self._inner.release(**kwargs)  # type: ignore[arg-type]


class _TenantScopedRetrieve:
    """Returns no evidence, or two sources that belong only to the caller."""

    def __init__(self) -> None:
        self.tenants: list[UUID] = []

    async def retrieve(self, tenant, request) -> RetrieveEvidenceResult:
        self.tenants.append(tenant.tenant_id)
        evidence: list[RetrievedEvidence] = []
        if request.question != "empty shelf":
            evidence = [
                _evidence(tenant.tenant_id, label="alpha", text="alpha source passage"),
                _evidence(tenant.tenant_id, label="beta", text="beta source passage"),
            ]
        mode = request.mode
        return RetrieveEvidenceResult(
            result=RetrievalResult(
                mode=mode,
                retrieval_trace_id=new_id(),
                evidence=evidence,
                warnings=[] if evidence else ["no_evidence_retrieved", "weak_evidence"],
            ),
            analysis=analyze_query(request.question, mode=mode),
        )


def _evidence(tenant_id: UUID, *, label: str, text: str) -> RetrievedEvidence:
    document_id = deterministic_id("search-doc", str(tenant_id), label)
    return RetrievedEvidence(
        chunk_id=deterministic_id("search-chunk", str(tenant_id), label),
        document_id=document_id,
        document_version_id=deterministic_id("search-version", str(tenant_id), label),
        document_name=f"{label}.pdf",
        page_start=1,
        page_end=2,
        section_path=["Results"],
        modality=Modality.TEXT,
        source_object_key=f"tenants/{tenant_id}/documents/{document_id}/original.pdf",
        text=text,
        score=0.9,
        score_components={"dense": 0.9},
    )


@pytest.fixture
def search_app(monkeypatch: pytest.MonkeyPatch):
    from graph_rag.config.settings import clear_settings_cache

    monkeypatch.setenv("AUTH_ENABLED", "false")
    clear_settings_cache()
    container = build_local_container()
    quotas = _AsyncQuota(container.quotas)
    container.quotas = quotas
    retrieve = _TenantScopedRetrieve()
    container.retrieve = retrieve
    try:
        yield create_app(container), quotas, retrieve
    finally:
        clear_settings_cache()


def test_async_quota_search_returns_zero_and_multiple_sources(search_app) -> None:
    app, quotas, retrieve = search_app
    client = TestClient(app)
    demo = {"X-Tenant-Key": "demo", "X-Correlation-ID": str(new_id())}
    other = {"X-Tenant-Key": "other", "X-Correlation-ID": str(new_id())}

    empty = client.post(
        "/api/v1/retrieval/search",
        headers=demo,
        json={"question": "empty shelf", "mode": "naive", "rerank": False},
    )
    assert empty.status_code == 200, empty.text
    empty_body = empty.json()
    assert empty_body["evidence"] == []
    assert "no_evidence_retrieved" in empty_body["warnings"]
    assert empty_body["retrieval_trace_id"]

    demo_hit = client.post(
        "/api/v1/retrieval/search",
        headers=demo,
        json={"question": "storage temperature", "mode": "naive", "rerank": False},
    )
    assert demo_hit.status_code == 200, demo_hit.text
    demo_evidence = demo_hit.json()["evidence"]
    assert len(demo_evidence) == 2
    demo_ids = {item["document_id"] for item in demo_evidence}
    assert {item["text"] for item in demo_evidence} == {
        "alpha source passage",
        "beta source passage",
    }
    assert all(item["source_object_key"].startswith("tenants/") for item in demo_evidence)
    assert all(item["document_name"] in {"alpha.pdf", "beta.pdf"} for item in demo_evidence)

    other_hit = client.post(
        "/api/v1/retrieval/search",
        headers=other,
        json={"question": "storage temperature", "mode": "naive", "rerank": False},
    )
    assert other_hit.status_code == 200, other_hit.text
    other_evidence = other_hit.json()["evidence"]
    assert len(other_evidence) == 2
    other_ids = {item["document_id"] for item in other_evidence}
    assert demo_ids.isdisjoint(other_ids)
    assert len(retrieve.tenants) == 3
    assert len(set(retrieve.tenants)) == 2
    assert quotas.reserve_calls == 3
    assert quotas.commit_calls == 3
    assert quotas.release_calls == 0


@pytest.mark.asyncio
async def test_vector_search_hides_other_tenant_chunks() -> None:
    owner = TenantContext(tenant_id=new_id(), tenant_key="owner")
    stranger = TenantContext(tenant_id=new_id(), tenant_key="stranger")
    store = InMemoryChunkVectorStore()
    await store.ensure_collection(vector_size=2)
    owner_doc = new_id()
    stranger_doc = new_id()
    await store.upsert(
        owner,
        [
            _vector(owner, owner_doc, "owner-a"),
            _vector(owner, owner_doc, "owner-b"),
        ],
    )
    await store.upsert(stranger, [_vector(stranger, stranger_doc, "stranger")])

    owner_hits = await store.search(
        owner,
        VectorSearchRequest(tenant_id=owner.tenant_id, query_vector=[1.0, 0.0], top_k=10),
    )
    stranger_hits = await store.search(
        stranger,
        VectorSearchRequest(tenant_id=stranger.tenant_id, query_vector=[1.0, 0.0], top_k=10),
    )
    assert {hit.payload.document_id for hit in owner_hits} == {owner_doc}
    assert len(owner_hits) == 2
    assert {hit.payload.document_id for hit in stranger_hits} == {stranger_doc}
    assert all(hit.payload.tenant_id == stranger.tenant_id for hit in stranger_hits)


def _vector(tenant: TenantContext, document_id: UUID, label: str) -> ChunkVectorRecord:
    chunk_id = deterministic_id("vec", str(tenant.tenant_id), label)
    return ChunkVectorRecord(
        point_id=chunk_id,
        content_vector=[1.0, 0.0],
        payload=ChunkVectorPayload(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=deterministic_id("vec-version", str(document_id)),
            chunk_id=chunk_id,
            modality=Modality.TEXT,
            chunk_type=ChunkType.TEXT,
            page_start=1,
            page_end=1,
            content_hash=content_sha256_hex(label),
            text_preview=label,
        ),
    )
