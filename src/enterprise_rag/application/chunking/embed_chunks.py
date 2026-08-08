"""Embed chunks and prepare vector-store records."""

from __future__ import annotations

from dataclasses import dataclass, field

from enterprise_rag.domain.chunks.models import ChunkBase, ChunkType
from enterprise_rag.domain.chunks.vectors import ChunkVectorPayload, ChunkVectorRecord
from enterprise_rag.domain.models.contracts import EmbeddingRequest
from enterprise_rag.domain.models.protocols import EmbeddingModel


@dataclass
class EmbedChunksResult:
    """Embedded chunk records ready for indexing."""

    records: list[ChunkVectorRecord] = field(default_factory=list)
    model_name: str | None = None


class EmbedChunksService:
    """Embed parent/child chunks via the application embedding protocol."""

    def __init__(
        self,
        embedding_model: EmbeddingModel,
        *,
        batch_size: int = 32,
        include_parents: bool = True,
        embed_summary_for_parents: bool = True,
    ) -> None:
        self._embedding_model = embedding_model
        self._batch_size = max(1, batch_size)
        self._include_parents = include_parents
        self._embed_summary_for_parents = embed_summary_for_parents

    async def embed(
        self,
        chunks: list[ChunkBase],
        *,
        language: str | None = None,
        parser: str | None = None,
    ) -> EmbedChunksResult:
        selected = [
            chunk
            for chunk in chunks
            if self._include_parents or chunk.parent_chunk_id is not None
        ]
        if not selected:
            return EmbedChunksResult(records=[])

        content_vectors = await self._embed_texts([chunk.text for chunk in selected])
        summary_vectors: list[list[float] | None] = [None] * len(selected)
        if self._embed_summary_for_parents:
            parent_indexes = [
                index
                for index, chunk in enumerate(selected)
                if chunk.chunk_type is ChunkType.SECTION and chunk.parent_chunk_id is None
            ]
            if parent_indexes:
                summaries = [
                    selected[index].text[:1200] for index in parent_indexes
                ]
                embedded = await self._embed_texts(summaries)
                for offset, index in enumerate(parent_indexes):
                    summary_vectors[index] = embedded[offset]

        records: list[ChunkVectorRecord] = []
        for index, chunk in enumerate(selected):
            preview = chunk.text[:2000]
            records.append(
                ChunkVectorRecord(
                    point_id=chunk.chunk_id,
                    content_vector=content_vectors[index],
                    summary_vector=summary_vectors[index],
                    payload=ChunkVectorPayload(
                        tenant_id=chunk.tenant_id,
                        document_id=chunk.document_id,
                        version_id=chunk.version_id,
                        chunk_id=chunk.chunk_id,
                        parent_chunk_id=chunk.parent_chunk_id,
                        modality=chunk.modality,
                        chunk_type=chunk.chunk_type,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        section_path=list(chunk.section_path),
                        content_hash=chunk.content_hash,
                        source_object_keys=list(chunk.source_object_keys),
                        text_preview=preview,
                        language=language,
                        parser=parser,
                        metadata=dict(chunk.metadata),
                    ),
                )
            )
        return EmbedChunksResult(records=records)

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            response = await self._embedding_model.embed(EmbeddingRequest(texts=batch))
            if len(response.vectors) != len(batch):
                msg = "Embedding provider returned mismatched vector count"
                raise RuntimeError(msg)
            vectors.extend(response.vectors)
        return vectors
