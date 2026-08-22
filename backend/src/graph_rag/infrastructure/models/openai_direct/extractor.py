"""Structured JSON extraction via chat/completions models."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel

from graph_rag.domain.models.contracts import (
    ChatMessage,
    ExtractionRequest,
    GenerationRequest,
    MessageRole,
    ModelRole,
    TextContentPart,
)
from graph_rag.domain.models.protocols import ChatModel
from graph_rag.shared.exceptions import ModelError

TModel = TypeVar("TModel", bound=BaseModel)


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


class ChatStructuredExtractor:
    """Adapter that asks a chat model for JSON matching a Pydantic schema."""

    def __init__(self, chat: ChatModel, *, model_name: str | None = None) -> None:
        self._chat = chat
        self._model_name = model_name

    async def extract(
        self,
        request: ExtractionRequest,
        output_schema: type[TModel],
    ) -> TModel:
        schema = output_schema.model_json_schema()
        schema_text = json.dumps(schema, ensure_ascii=True)
        system = (
            "Extract structured data. Return ONLY valid JSON matching the schema. "
            "Do not invent facts that are not supported by the source text."
        )
        user_parts: list[str] = [
            f"JSON schema:\n{schema_text}",
            "Source messages:",
        ]
        for message in request.messages:
            if isinstance(message.content, str):
                user_parts.append(f"{message.role.value}: {message.content}")
            else:
                texts = [
                    part.text
                    for part in message.content
                    if isinstance(part, TextContentPart) or getattr(part, "type", None) == "text"
                ]
                user_parts.append(f"{message.role.value}: " + "\n".join(texts))
        try:
            response = await self._chat.generate(
                GenerationRequest(
                    messages=[
                        ChatMessage(role=MessageRole.SYSTEM, content=system),
                        ChatMessage(role=MessageRole.USER, content="\n\n".join(user_parts)),
                    ],
                    role=ModelRole.EXTRACTION,
                    model_name=request.model_name or self._model_name,
                    temperature=request.temperature if request.temperature is not None else 0.0,
                    prompt_version=request.prompt_version,
                    correlation_id=request.correlation_id,
                )
            )
            payload = json.loads(_strip_fences(response.text))
            return output_schema.model_validate(payload)
        except Exception as exc:
            raise ModelError(
                "Structured extraction failed",
                details={"schema": output_schema.__name__},
                cause=exc,
            ) from exc


__all__ = ["ChatStructuredExtractor"]
