"""Qdrant chunk vector repository."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from enterprise_rag.config.settings import QdrantSettings
from enterprise_rag.domain.chunks.models import ChunkType
from enterprise_rag.domain.chunks.vectors import (
    ChunkVectorPayload,
    ChunkVectorRecord,
    VectorSearchHit,
    VectorSearchRequest,
)
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import AuthorizationError, ConfigurationError, StorageError


class QdrantChunkVectorStore:
    """Qdrant adapter for ``rag_chunks`` with named ``content``/``summary`` vectors."""

    def __init__(
        self,
        settings: QdrantSettings | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self._settings = settings or QdrantSettings()
        self._client = client
        self._collection = self._settings.collection_chunks

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise ConfigurationError(
                "Optional dependency 'qdrant_client' is not installed",
                details={"extra": "qdrant", "module": "qdrant_client"},
                cause=exc,
            ) from exc
        kwargs: dict[str, Any] = {
            "url": self._settings.url,
            "check_compatibility": False,
        }
        if self._settings.api_key is not None:
            kwargs["api_key"] = self._settings.api_key.get_secret_value()
        self._client = QdrantClient(**kwargs)
        return self._client

    async def ensure_collection(self, *, vector_size: int) -> None:
        client = self._get_client()
        try:
            from qdrant_client.http import models as qm
        except ImportError as exc:
            raise ConfigurationError(
                "qdrant_client models unavailable",
                cause=exc,
            ) from exc

        existing = {collection.name for collection in client.get_collections().collections}
        if self._collection in existing:
            return
        client.create_collection(
            collection_name=self._collection,
            vectors_config={
                "content": qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
                "summary": qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
            },
        )
        for field_name, schema in (
            ("tenant_id", qm.PayloadSchemaType.KEYWORD),
            ("document_id", qm.PayloadSchemaType.KEYWORD),
            ("version_id", qm.PayloadSchemaType.KEYWORD),
            ("modality", qm.PayloadSchemaType.KEYWORD),
            ("chunk_type", qm.PayloadSchemaType.KEYWORD),
        ):
            client.create_payload_index(
                collection_name=self._collection,
                field_name=field_name,
                field_schema=schema,
            )

    async def upsert(
        self,
        tenant: TenantContext,
        records: list[ChunkVectorRecord],
    ) -> int:
        if not records:
            return 0
        client = self._get_client()
        try:
            from qdrant_client.http import models as qm
        except ImportError as exc:
            raise ConfigurationError("qdrant_client models unavailable", cause=exc) from exc

        points: list[Any] = []
        for record in records:
            if record.payload.tenant_id != tenant.tenant_id:
                raise AuthorizationError("Vector record tenant mismatch")
            vectors: dict[str, list[float]] = {"content": record.content_vector}
            if record.summary_vector is not None:
                vectors["summary"] = record.summary_vector
            else:
                vectors["summary"] = record.content_vector
            points.append(
                qm.PointStruct(
                    id=str(record.point_id),
                    vector=vectors,
                    payload=_payload_dict(record.payload),
                )
            )
        try:
            client.upsert(collection_name=self._collection, points=points, wait=True)
        except Exception as exc:
            raise StorageError("Qdrant upsert failed", cause=exc) from exc
        return len(points)

    async def search(
        self,
        tenant: TenantContext,
        request: VectorSearchRequest,
    ) -> list[VectorSearchHit]:
        if request.tenant_id != tenant.tenant_id:
            raise AuthorizationError("Search tenant_id must match tenant context")
        client = self._get_client()
        try:
            from qdrant_client.http import models as qm
        except ImportError as exc:
            raise ConfigurationError("qdrant_client models unavailable", cause=exc) from exc

        must: list[Any] = [
            qm.FieldCondition(
                key="tenant_id",
                match=qm.MatchValue(value=str(tenant.tenant_id)),
            )
        ]
        if request.document_ids:
            must.append(
                qm.FieldCondition(
                    key="document_id",
                    match=qm.MatchAny(any=[str(item) for item in request.document_ids]),
                )
            )
        if request.modalities:
            must.append(
                qm.FieldCondition(
                    key="modality",
                    match=qm.MatchAny(any=[item.value for item in request.modalities]),
                )
            )
        try:
            # qdrant-client >=1.14 uses query_points; older clients expose search().
            if hasattr(client, "query_points"):
                response = client.query_points(
                    collection_name=self._collection,
                    query=list(request.query_vector),
                    using=request.vector_name,
                    query_filter=qm.Filter(must=must),
                    limit=request.top_k,
                    with_payload=True,
                )
                results = list(getattr(response, "points", []) or [])
            else:
                results = client.search(
                    collection_name=self._collection,
                    query_vector=(request.vector_name, request.query_vector),
                    query_filter=qm.Filter(must=must),
                    limit=request.top_k,
                    with_payload=True,
                )
        except Exception as exc:
            raise StorageError("Qdrant search failed", cause=exc) from exc

        hits: list[VectorSearchHit] = []
        for point in results:
            payload = _payload_from_dict(dict(point.payload or {}))
            hits.append(
                VectorSearchHit(
                    point_id=UUID(str(point.id)),
                    score=float(point.score),
                    payload=payload,
                )
            )
        return hits

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> int:
        client = self._get_client()
        try:
            from qdrant_client.http import models as qm
        except ImportError as exc:
            raise ConfigurationError("qdrant_client models unavailable", cause=exc) from exc
        try:
            result = client.delete(
                collection_name=self._collection,
                points_selector=qm.FilterSelector(
                    filter=qm.Filter(
                        must=[
                            qm.FieldCondition(
                                key="tenant_id",
                                match=qm.MatchValue(value=str(tenant.tenant_id)),
                            ),
                            qm.FieldCondition(
                                key="document_id",
                                match=qm.MatchValue(value=str(document_id)),
                            ),
                            qm.FieldCondition(
                                key="version_id",
                                match=qm.MatchValue(value=str(version_id)),
                            ),
                        ]
                    )
                ),
                wait=True,
            )
        except Exception as exc:
            raise StorageError("Qdrant delete failed", cause=exc) from exc
        status = getattr(result, "status", None)
        return 0 if status is None else 1


def _payload_dict(payload: ChunkVectorPayload) -> dict[str, Any]:
    return {
        "tenant_id": str(payload.tenant_id),
        "document_id": str(payload.document_id),
        "version_id": str(payload.version_id),
        "chunk_id": str(payload.chunk_id),
        "parent_chunk_id": str(payload.parent_chunk_id) if payload.parent_chunk_id else None,
        "modality": payload.modality.value,
        "chunk_type": payload.chunk_type.value,
        "page_start": payload.page_start,
        "page_end": payload.page_end,
        "section_path": list(payload.section_path),
        "content_hash": payload.content_hash,
        "source_object_keys": list(payload.source_object_keys),
        "text_preview": payload.text_preview,
        "language": payload.language,
        "parser": payload.parser,
        "security_labels": list(payload.security_labels),
        "metadata": payload.metadata,
    }


def _payload_from_dict(data: dict[str, Any]) -> ChunkVectorPayload:
    parent = data.get("parent_chunk_id")
    return ChunkVectorPayload(
        tenant_id=UUID(str(data["tenant_id"])),
        document_id=UUID(str(data["document_id"])),
        version_id=UUID(str(data["version_id"])),
        chunk_id=UUID(str(data["chunk_id"])),
        parent_chunk_id=UUID(str(parent)) if parent else None,
        modality=Modality(str(data["modality"])),
        chunk_type=ChunkType(str(data["chunk_type"])),
        page_start=int(data.get("page_start", 1)),
        page_end=int(data.get("page_end", 1)),
        section_path=[str(item) for item in data.get("section_path", [])],
        content_hash=str(data["content_hash"]),
        source_object_keys=[str(item) for item in data.get("source_object_keys", [])],
        text_preview=str(data.get("text_preview", "")),
        language=str(data["language"]) if data.get("language") else None,
        parser=str(data["parser"]) if data.get("parser") else None,
        security_labels=[str(item) for item in data.get("security_labels", [])],
        metadata=dict(data.get("metadata") or {}),
    )
