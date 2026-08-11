"""Direct OpenAI SDK embedding adapter."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence

from enterprise_rag.application.usage.record import record_model_usage
from enterprise_rag.domain.models.contracts import (
    EmbeddingRequest,
    EmbeddingResponse,
    ModelCallMetadata,
    ModelRole,
    TokenUsage,
)
from enterprise_rag.domain.usage.protocols import UsageRecorder
from enterprise_rag.shared.exceptions import ConfigurationError, ModelError

EmbedBatchFn = Callable[[list[str]], tuple[list[list[float]], TokenUsage]]


def _default_openai_embed(
    texts: list[str], *, model_name: str, api_key: str | None
) -> tuple[list[list[float]], TokenUsage]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ConfigurationError(
            "Optional dependency 'openai' is not installed",
            details={"extra": "llm", "module": "openai"},
            cause=exc,
        ) from exc
    client = OpenAI(api_key=api_key)
    response = client.embeddings.create(model=model_name, input=texts)
    vectors = [list(item.embedding) for item in response.data]
    usage = response.usage
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage is not None else 0
    total = int(getattr(usage, "total_tokens", 0) or prompt) if usage is not None else prompt
    token_usage = TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=0,
        total_tokens=total,
    )
    return vectors, token_usage


class OpenAIEmbeddingModel:
    """``EmbeddingModel`` backed by the official OpenAI SDK."""

    def __init__(
        self,
        *,
        model_name: str = "text-embedding-3-small",
        api_key: str | None = None,
        embed_fn: EmbedBatchFn | None = None,
        usage_recorder: UsageRecorder | None = None,
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key
        self._embed_fn = embed_fn
        self._usage_recorder = usage_recorder

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        model_name = request.model_name or self._model_name
        started = time.perf_counter()
        try:
            if self._embed_fn is not None:
                result = self._embed_fn(list(request.texts))
                if (
                    isinstance(result, tuple)
                    and len(result) == 2
                    and isinstance(result[1], TokenUsage)
                ):
                    vectors, usage = result
                else:
                    vectors = result  # type: ignore[assignment]
                    usage = TokenUsage()
            else:
                vectors, usage = await asyncio.to_thread(
                    _default_openai_embed,
                    list(request.texts),
                    model_name=model_name,
                    api_key=self._api_key,
                )
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ModelError("OpenAI embedding failed", cause=exc) from exc
        latency_ms = (time.perf_counter() - started) * 1000.0
        await record_model_usage(
            self._usage_recorder,
            provider="openai",
            model_name=model_name,
            role=ModelRole.EMBEDDING,
            usage=usage,
            latency_ms=latency_ms,
            correlation_id=request.correlation_id,
        )
        return EmbeddingResponse(
            vectors=vectors,
            call=ModelCallMetadata(
                provider="openai",
                model_name=model_name,
                role=ModelRole.EMBEDDING,
                correlation_id=request.correlation_id,
                latency_ms=latency_ms,
                usage=usage,
            ),
        )

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self.embed(EmbeddingRequest(texts=list(texts)))
        return response.vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]


__all__ = ["OpenAIEmbeddingModel"]
