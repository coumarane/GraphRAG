"""Plain conversational chat: no retrieval, no citations."""

from __future__ import annotations

from dataclasses import dataclass, field

from graph_rag.application.generation.prompts import (
    CHAT_PROMPT_VERSION,
    build_chat_messages,
)
from graph_rag.domain.models.contracts import GenerationRequest, ModelRole
from graph_rag.domain.models.protocols import ChatModel
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ChatResult:
    """Plain chat answer, no citations/retrieval metadata."""

    answer: str
    warnings: list[str] = field(default_factory=list)


class ChatConversationService:
    """Generate an ungrounded conversational reply from the same chat model."""

    def __init__(self, chat_model: ChatModel, *, temperature: float = 0.3) -> None:
        self._chat = chat_model
        self._temperature = temperature

    async def chat(
        self,
        tenant: TenantContext,
        *,
        question: str,
        history: list[dict[str, str]],
    ) -> ChatResult:
        messages = build_chat_messages(question=question, history=history)
        generation = await self._chat.generate(
            GenerationRequest(
                messages=messages,
                role=ModelRole.ANSWER,
                temperature=self._temperature,
                prompt_version=CHAT_PROMPT_VERSION,
                metadata={"tenant_id": str(tenant.tenant_id)},
            )
        )
        logger.info("chat_completed", tenant_id=str(tenant.tenant_id))
        return ChatResult(answer=generation.text)
