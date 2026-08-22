"""Provider protocol structural tests (no SDK imports)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import get_type_hints

from pydantic import BaseModel

from graph_rag.domain.models import (
    ChatModel,
    EmbeddingModel,
    EmbeddingRequest,
    EmbeddingResponse,
    ExtractionRequest,
    GenerationRequest,
    GenerationResponse,
    ModelCallMetadata,
    ModelRole,
    StructuredExtractor,
    TokenUsage,
    VisionModel,
    VisionRequest,
    VisionResponse,
)


class _FakeChat:
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(
            text="ok",
            call=ModelCallMetadata(
                provider="fake",
                model_name="fake-text",
                role=ModelRole.TEXT,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            ),
        )


class _FakeVision:
    async def generate(self, request: VisionRequest) -> VisionResponse:
        return VisionResponse(
            text="image ok",
            call=ModelCallMetadata(
                provider="fake",
                model_name="fake-vision",
                role=ModelRole.VISION,
            ),
        )


class _FakeEmbed:
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            vectors=[[0.1, 0.2] for _ in request.texts],
            call=ModelCallMetadata(
                provider="fake",
                model_name="fake-embed",
                role=ModelRole.EMBEDDING,
            ),
        )

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2]


class _Out(BaseModel):
    value: str


class _FakeExtractor:
    async def extract(self, request: ExtractionRequest, output_schema: type[_Out]) -> _Out:
        return output_schema(value="x")


def test_protocol_runtime_assignment() -> None:
    chat: ChatModel = _FakeChat()
    vision: VisionModel = _FakeVision()
    embed: EmbeddingModel = _FakeEmbed()
    extractor: StructuredExtractor = _FakeExtractor()
    assert chat is not None
    assert vision is not None
    assert embed is not None
    assert extractor is not None


def test_generation_request_requires_messages() -> None:
    hints = get_type_hints(GenerationRequest)
    assert "messages" in hints
