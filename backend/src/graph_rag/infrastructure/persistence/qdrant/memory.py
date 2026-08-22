"""In-memory chunk vector store for unit tests."""

from __future__ import annotations

from uuid import UUID

from graph_rag.domain.chunks.vectors import (
    ChunkVectorRecord,
    VectorSearchHit,
    VectorSearchRequest,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import AuthorizationError, StorageError


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


class InMemoryChunkVectorStore:
    """Simple cosine/dot-product vector index with tenant isolation."""

    def __init__(self) -> None:
        self._records: dict[UUID, ChunkVectorRecord] = {}
        self._vector_size: int | None = None

    async def ensure_collection(self, *, vector_size: int) -> None:
        if vector_size < 1:
            raise StorageError("vector_size must be >= 1")
        if self._vector_size is None:
            self._vector_size = vector_size
        elif self._vector_size != vector_size:
            raise StorageError(
                "Incompatible vector size",
                details={"expected": self._vector_size, "got": vector_size},
            )

    async def upsert(
        self,
        tenant: TenantContext,
        records: list[ChunkVectorRecord],
    ) -> int:
        written = 0
        for record in records:
            self._assert_tenant(tenant, record.payload.tenant_id)
            if self._vector_size is None:
                self._vector_size = len(record.content_vector)
            elif len(record.content_vector) != self._vector_size:
                raise StorageError(
                    "Record vector size mismatch",
                    details={
                        "expected": self._vector_size,
                        "got": len(record.content_vector),
                    },
                )
            self._records[record.point_id] = record
            written += 1
        return written

    async def search(
        self,
        tenant: TenantContext,
        request: VectorSearchRequest,
    ) -> list[VectorSearchHit]:
        if request.tenant_id != tenant.tenant_id:
            raise AuthorizationError("Search tenant_id must match tenant context")
        hits: list[VectorSearchHit] = []
        for record in self._records.values():
            payload = record.payload
            if payload.tenant_id != tenant.tenant_id:
                continue
            if request.document_ids and payload.document_id not in request.document_ids:
                continue
            if request.modalities and payload.modality not in request.modalities:
                continue
            vector = (
                record.summary_vector
                if request.vector_name == "summary" and record.summary_vector
                else record.content_vector
            )
            score = _dot(request.query_vector, vector)
            hits.append(
                VectorSearchHit(point_id=record.point_id, score=score, payload=payload)
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[: request.top_k]

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> int:
        to_delete = [
            point_id
            for point_id, record in self._records.items()
            if record.payload.tenant_id == tenant.tenant_id
            and record.payload.document_id == document_id
            and record.payload.version_id == version_id
        ]
        for point_id in to_delete:
            del self._records[point_id]
        return len(to_delete)

    async def delete_document(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
    ) -> int:
        to_delete = [
            point_id
            for point_id, record in self._records.items()
            if record.payload.tenant_id == tenant.tenant_id
            and record.payload.document_id == document_id
        ]
        for point_id in to_delete:
            del self._records[point_id]
        return len(to_delete)

    @staticmethod
    def _assert_tenant(tenant: TenantContext, payload_tenant_id: UUID) -> None:
        if tenant.tenant_id != payload_tenant_id:
            raise AuthorizationError("Vector record tenant mismatch")
