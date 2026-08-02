"""Direct OpenAI SDK embedding adapter."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from enterprise_rag.domain.models.contracts import (
    EmbeddingRequest,
    EmbeddingResponse,
    ModelCallMetadata,
    ModelRole,
    TokenUsage,
)
from enterprise_rag.shared.exceptions import ConfigurationError, ModelError

EmbedBatchFn = Callable[[list[str]], list[list[float]]]


def _default_openai_embed(
    texts: list[str], *, model_name: str, api_key: str | None
) -> list[list[float]]:
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
    return [list(item.embedding) for item in response.data]


class OpenAIEmbeddingModel:
    """``EmbeddingModel`` backed by the official OpenAI SDK."""

    def __init__(
        self,
        *,
        model_name: str = "text-embedding-3-large",
        api_key: str | None = None,
        embed_fn: EmbedBatchFn | None = None,
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key
        self._embed_fn = embed_fn

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        model_name = request.model_name or self._model_name
        try:
            if self._embed_fn is not None:
                vectors = self._embed_fn(list(request.texts))
            else:
                vectors = _default_openai_embed(
                    list(request.texts),
                    model_name=model_name,
                    api_key=self._api_key,
                )
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ModelError("OpenAI embedding failed", cause=exc) from exc
        return EmbeddingResponse(
            vectors=vectors,
            call=ModelCallMetadata(
                provider="openai",
                model_name=model_name,
                role=ModelRole.EMBEDDING,
                correlation_id=request.correlation_id,
                usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            ),
        )

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self.embed(EmbeddingRequest(texts=list(texts)))
        return response.vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]
