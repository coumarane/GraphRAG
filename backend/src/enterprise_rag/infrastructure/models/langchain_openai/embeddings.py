"""LangChain OpenAI embedding adapter."""

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


def _default_langchain_embed(
    texts: list[str], *, model_name: str, api_key: str | None
) -> list[list[float]]:
    try:
        from langchain_openai import OpenAIEmbeddings
    except ImportError as exc:
        raise ConfigurationError(
            "Optional dependency 'langchain_openai' is not installed",
            details={"extra": "llm", "module": "langchain_openai"},
            cause=exc,
        ) from exc
    embeddings = OpenAIEmbeddings(model=model_name, api_key=api_key)
    result = embeddings.embed_documents(texts)
    return [list(vector) for vector in result]


class LangChainOpenAIEmbeddingModel:
    """``EmbeddingModel`` backed by langchain-openai (injectable for tests)."""

    def __init__(
        self,
        *,
        model_name: str = "text-embedding-3-small",
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
                vectors = _default_langchain_embed(
                    list(request.texts),
                    model_name=model_name,
                    api_key=self._api_key,
                )
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ModelError("LangChain embedding failed", cause=exc) from exc
        return EmbeddingResponse(
            vectors=vectors,
            call=ModelCallMetadata(
                provider="langchain_openai",
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
