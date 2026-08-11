"""Direct OpenAI SDK chat adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from enterprise_rag.domain.models.contracts import (
    ChatMessage,
    ContentPartType,
    GenerationRequest,
    GenerationResponse,
    ImageBytesContentPart,
    ImageUrlContentPart,
    ModelCallMetadata,
    ModelRole,
    TextContentPart,
    TokenUsage,
)
from enterprise_rag.shared.exceptions import ConfigurationError, ModelError

ChatCompleteFn = Callable[[list[dict[str, Any]], str, float], tuple[str, TokenUsage]]


def _message_to_openai(message: ChatMessage) -> dict[str, Any]:
    role = message.role.value
    if isinstance(message.content, str):
        return {"role": role, "content": message.content}
    parts: list[dict[str, Any]] = []
    for part in message.content:
        if isinstance(part, TextContentPart) or part.type is ContentPartType.TEXT:
            parts.append({"type": "text", "text": getattr(part, "text", "")})
        elif isinstance(part, ImageUrlContentPart) or part.type is ContentPartType.IMAGE_URL:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": getattr(part, "url", ""),
                        "detail": getattr(part, "detail", None) or "auto",
                    },
                }
            )
        elif isinstance(part, ImageBytesContentPart) or part.type is ContentPartType.IMAGE_BYTES:
            import base64

            encoded = base64.b64encode(part.data).decode("ascii")
            mime = part.mime_type or "image/png"
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{encoded}",
                        "detail": part.detail or "auto",
                    },
                }
            )
    return {"role": role, "content": parts}


def _default_openai_chat(
    messages: list[dict[str, Any]],
    *,
    model_name: str,
    api_key: str | None,
    temperature: float,
) -> tuple[str, TokenUsage]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ConfigurationError(
            "Optional dependency 'openai' is not installed",
            details={"extra": "llm", "module": "openai"},
            cause=exc,
        ) from exc
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
    )
    choice = response.choices[0].message
    text = choice.content or ""
    usage = response.usage
    token_usage = TokenUsage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )
    return text, token_usage


class OpenAIChatModel:
    """``ChatModel`` backed by the official OpenAI SDK."""

    def __init__(
        self,
        *,
        model_name: str = "gpt-4.1",
        api_key: str | None = None,
        temperature: float = 0.0,
        chat_fn: ChatCompleteFn | None = None,
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key
        self._temperature = temperature
        self._chat_fn = chat_fn

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        model_name = request.model_name or self._model_name
        temperature = (
            request.temperature if request.temperature is not None else self._temperature
        )
        payload = [_message_to_openai(message) for message in request.messages]
        try:
            if self._chat_fn is not None:
                text, usage = self._chat_fn(payload, model_name, temperature)
            else:
                text, usage = await asyncio.to_thread(
                    _default_openai_chat,
                    payload,
                    model_name=model_name,
                    api_key=self._api_key,
                    temperature=temperature,
                )
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ModelError("OpenAI chat completion failed", cause=exc) from exc
        return GenerationResponse(
            text=text,
            call=ModelCallMetadata(
                provider="openai",
                model_name=model_name,
                role=request.role or ModelRole.ANSWER,
                prompt_version=request.prompt_version,
                correlation_id=request.correlation_id,
                usage=usage,
            ),
        )


__all__ = ["OpenAIChatModel"]
