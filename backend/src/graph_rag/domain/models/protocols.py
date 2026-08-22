"""Application-owned model provider protocols.

Infrastructure adapters (LangChain OpenAI and direct OpenAI SDK) must implement
these interfaces. Domain and application code must not import provider SDKs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from graph_rag.domain.models.contracts import (
    EmbeddingRequest,
    EmbeddingResponse,
    ExtractionRequest,
    GenerationRequest,
    GenerationResponse,
    RerankRequest,
    RerankResponse,
    TokenCountRequest,
    TokenCountResponse,
    VisionRequest,
    VisionResponse,
)

TModel = TypeVar("TModel", bound=BaseModel)


@runtime_checkable
class ChatModel(Protocol):
    """Text chat generation provider."""

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Generate a text completion."""
        ...


@runtime_checkable
class VisionModel(Protocol):
    """Vision / multimodal generation provider."""

    async def generate(self, request: VisionRequest) -> VisionResponse:
        """Generate a vision-aware completion."""
        ...


@runtime_checkable
class StructuredExtractor(Protocol):
    """Structured output extraction provider."""

    async def extract(
        self,
        request: ExtractionRequest,
        output_schema: type[TModel],
    ) -> TModel:
        """Extract a validated Pydantic model from the prompt."""
        ...


@runtime_checkable
class EmbeddingModel(Protocol):
    """Embedding provider."""

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Embed a batch of texts."""
        ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed documents for indexing."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        ...


@runtime_checkable
class Reranker(Protocol):
    """Optional reranking provider."""

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        """Rerank candidates for a query."""
        ...


@runtime_checkable
class TokenCounter(Protocol):
    """Token estimation provider."""

    async def count(self, request: TokenCountRequest) -> TokenCountResponse:
        """Count tokens for the given text and model."""
        ...
