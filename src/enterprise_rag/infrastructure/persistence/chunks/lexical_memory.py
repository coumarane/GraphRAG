"""In-memory lexical / sparse search over chunk text."""

from __future__ import annotations

import math
import re
from collections import Counter
from uuid import UUID

from enterprise_rag.domain.chunks.models import ChunkBase
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.retrieval.protocols import LexicalHit
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import AuthorizationError

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_/]{1,}", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(text)]


class InMemoryLexicalSearchStore:
    """TF-style lexical ranking with tenant isolation."""

    def __init__(self) -> None:
        self._chunks: dict[UUID, ChunkBase] = {}
        self._tokens: dict[UUID, Counter[str]] = {}

    async def upsert(self, tenant: TenantContext, chunks: list[ChunkBase]) -> int:
        written = 0
        for chunk in chunks:
            if chunk.tenant_id != tenant.tenant_id:
                raise AuthorizationError("Chunk tenant mismatch")
            self._chunks[chunk.chunk_id] = chunk
            self._tokens[chunk.chunk_id] = Counter(_tokenize(chunk.text))
            written += 1
        return written

    async def search(
        self,
        tenant: TenantContext,
        *,
        query: str,
        top_k: int = 12,
        document_ids: list[UUID] | None = None,
        modalities: list[Modality] | None = None,
    ) -> list[LexicalHit]:
        query_tokens = Counter(_tokenize(query))
        if not query_tokens:
            return []
        doc_filter = set(document_ids or [])
        modality_filter = set(modalities or [])
        hits: list[LexicalHit] = []
        for chunk_id, chunk in self._chunks.items():
            if chunk.tenant_id != tenant.tenant_id:
                continue
            if doc_filter and chunk.document_id not in doc_filter:
                continue
            if modality_filter and chunk.modality not in modality_filter:
                continue
            tokens = self._tokens.get(chunk_id, Counter())
            if not tokens:
                continue
            score = 0.0
            doc_len = sum(tokens.values())
            for term, qtf in query_tokens.items():
                tf = tokens.get(term, 0)
                if tf <= 0:
                    continue
                # Simple TF scoring with mild length normalization.
                score += qtf * (1.0 + math.log(tf)) / math.sqrt(doc_len)
            if score > 0:
                hits.append(LexicalHit(chunk_id=chunk_id, score=score))
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[:top_k]
