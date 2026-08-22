"""Qdrant-backed chunk lookup so retrieval survives API restarts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from graph_rag.domain.chunks.models import ChunkBase
from graph_rag.domain.chunks.vectors import ChunkVectorPayload
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import AuthorizationError, ConfigurationError, StorageError


def chunk_from_payload(payload: ChunkVectorPayload) -> ChunkBase:
    """Rebuild a chunk from a durable vector payload."""
    metadata = dict(payload.metadata)
    if payload.language and "language" not in metadata:
        metadata["language"] = payload.language
    if payload.parser and "parser" not in metadata:
        metadata["parser"] = payload.parser
    text = payload.text_preview or ""
    return ChunkBase(
        chunk_id=payload.chunk_id,
        tenant_id=payload.tenant_id,
        document_id=payload.document_id,
        version_id=payload.version_id,
        parent_chunk_id=payload.parent_chunk_id,
        modality=payload.modality,
        chunk_type=payload.chunk_type,
        text=text,
        token_count=max(1, (len(text) + 3) // 4) if text else 0,
        page_start=payload.page_start,
        page_end=payload.page_end,
        section_path=list(payload.section_path),
        source_object_keys=list(payload.source_object_keys),
        content_hash=payload.content_hash,
        metadata=metadata,
    )


class QdrantChunkLookupStore:
    """Chunk SoR reconstructed from Qdrant payloads (+ process-local write cache)."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        collection: str = "rag_chunks",
        settings: Any | None = None,
    ) -> None:
        self._client = client
        self._collection = collection
        self._settings = settings
        self._cache: dict[UUID, ChunkBase] = {}

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
        if self._settings is None:
            from graph_rag.config.settings import QdrantSettings

            self._settings = QdrantSettings()
        kwargs: dict[str, Any] = {
            "url": self._settings.url,
            "check_compatibility": False,
        }
        if self._settings.api_key is not None:
            kwargs["api_key"] = self._settings.api_key.get_secret_value()
        self._client = QdrantClient(**kwargs)
        self._collection = self._settings.collection_chunks
        return self._client

    @staticmethod
    def _payload_to_chunk(raw: dict[str, Any]) -> ChunkBase | None:
        try:
            payload = ChunkVectorPayload.model_validate(raw)
        except Exception:
            return None
        return chunk_from_payload(payload)

    async def upsert(self, tenant: TenantContext, chunks: list[ChunkBase]) -> int:
        written = 0
        for chunk in chunks:
            if chunk.tenant_id != tenant.tenant_id:
                raise AuthorizationError("Chunk tenant mismatch")
            self._cache[chunk.chunk_id] = chunk
            written += 1
        return written

    async def get_chunks(
        self,
        tenant: TenantContext,
        chunk_ids: list[UUID],
    ) -> list[ChunkBase]:
        found: list[ChunkBase] = []
        missing: list[UUID] = []
        for chunk_id in chunk_ids:
            cached = self._cache.get(chunk_id)
            if cached is not None:
                if cached.tenant_id != tenant.tenant_id:
                    raise AuthorizationError("Chunk tenant mismatch on lookup")
                found.append(cached)
            else:
                missing.append(chunk_id)
        if not missing:
            return found

        client = self._get_client()
        try:
            points = client.retrieve(
                collection_name=self._collection,
                ids=[str(item) for item in missing],
                with_payload=True,
            )
        except Exception as exc:
            raise StorageError("Qdrant chunk retrieve failed", cause=exc) from exc

        by_id: dict[UUID, ChunkBase] = {}
        for point in points:
            payload = dict(point.payload or {})
            chunk = self._payload_to_chunk(payload)
            if chunk is None:
                continue
            if chunk.tenant_id != tenant.tenant_id:
                raise AuthorizationError("Chunk tenant mismatch on lookup")
            by_id[chunk.chunk_id] = chunk
            self._cache[chunk.chunk_id] = chunk
        for chunk_id in missing:
            chunk = by_id.get(chunk_id)
            if chunk is not None:
                found.append(chunk)
        return found

    def as_map(self, tenant: TenantContext) -> dict[UUID, ChunkBase]:
        # Prefer cache; lazily enrich from Qdrant only for cached tenant docs.
        return {
            chunk_id: chunk
            for chunk_id, chunk in self._cache.items()
            if chunk.tenant_id == tenant.tenant_id
        }

    def list_for_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> list[ChunkBase]:
        cached = [
            chunk
            for chunk in self._cache.values()
            if chunk.tenant_id == tenant.tenant_id
            and chunk.document_id == document_id
            and chunk.version_id == version_id
        ]
        if cached:
            return sorted(cached, key=lambda item: (item.page_start, item.page_end, str(item.chunk_id)))

        client = self._get_client()
        try:
            from qdrant_client.http import models as qm
        except ImportError as exc:
            raise ConfigurationError("qdrant_client models unavailable", cause=exc) from exc

        must = [
            qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=str(tenant.tenant_id))),
            qm.FieldCondition(key="document_id", match=qm.MatchValue(value=str(document_id))),
            qm.FieldCondition(key="version_id", match=qm.MatchValue(value=str(version_id))),
        ]
        chunks: list[ChunkBase] = []
        offset = None
        try:
            while True:
                batch, offset = client.scroll(
                    collection_name=self._collection,
                    scroll_filter=qm.Filter(must=must),
                    limit=128,
                    offset=offset,
                    with_payload=True,
                )
                for point in batch:
                    chunk = self._payload_to_chunk(dict(point.payload or {}))
                    if chunk is None:
                        continue
                    self._cache[chunk.chunk_id] = chunk
                    chunks.append(chunk)
                if offset is None:
                    break
        except Exception as exc:
            raise StorageError("Qdrant chunk scroll failed", cause=exc) from exc
        return sorted(chunks, key=lambda item: (item.page_start, item.page_end, str(item.chunk_id)))

    async def delete_version(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        version_id: UUID,
    ) -> int:
        to_delete = [
            chunk_id
            for chunk_id, chunk in self._cache.items()
            if chunk.tenant_id == tenant.tenant_id
            and chunk.document_id == document_id
            and chunk.version_id == version_id
        ]
        for chunk_id in to_delete:
            del self._cache[chunk_id]
        return len(to_delete)

    def hydrate_from_qdrant(
        self,
        tenant: TenantContext,
        *,
        document_ids: list[UUID] | None = None,
        limit: int = 10_000,
    ) -> int:
        """Load payloads into the process cache (and return count)."""
        client = self._get_client()
        try:
            from qdrant_client.http import models as qm
        except ImportError as exc:
            raise ConfigurationError("qdrant_client models unavailable", cause=exc) from exc

        must = [
            qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=str(tenant.tenant_id))),
        ]
        if document_ids:
            must.append(
                qm.FieldCondition(
                    key="document_id",
                    match=qm.MatchAny(any=[str(item) for item in document_ids]),
                )
            )
        loaded = 0
        offset = None
        while loaded < limit:
            batch, offset = client.scroll(
                collection_name=self._collection,
                scroll_filter=qm.Filter(must=must),
                limit=min(256, limit - loaded),
                offset=offset,
                with_payload=True,
            )
            for point in batch:
                chunk = self._payload_to_chunk(dict(point.payload or {}))
                if chunk is None:
                    continue
                self._cache[chunk.chunk_id] = chunk
                loaded += 1
            if offset is None or not batch:
                break
        return loaded
