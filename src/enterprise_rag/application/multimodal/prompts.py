"""Shared helpers for multimodal processors."""

from __future__ import annotations

from enterprise_rag.domain.elements.context import ElementContext
from enterprise_rag.domain.elements.models import DocumentElement
from enterprise_rag.domain.models.contracts import (
    ChatMessage,
    ContentPart,
    ExtractionRequest,
    ImageBytesContentPart,
    MessageRole,
    ModelCallMetadata,
    ModelRole,
    TextContentPart,
)
from enterprise_rag.domain.security import (
    DOCUMENT_CONTEXT_END,
    DOCUMENT_CONTEXT_START,
    TRUST_BOUNDARY_NOTICE,
)
from enterprise_rag.domain.types import JsonValue


def context_as_prompt(context: ElementContext) -> str:
    """Serialize element context into delimited untrusted document data."""
    lines = [
        DOCUMENT_CONTEXT_START,
        f"title: {context.document_title or ''}",
        f"document_type: {context.document_type or ''}",
        f"page: {context.page_number}",
        f"section: {' / '.join(context.section_path)}",
        f"heading: {context.heading or ''}",
        f"caption: {context.caption or ''}",
        "preceding:",
        context.preceding_text or "",
        "following:",
        context.following_text or "",
    ]
    if context.nearby_element_summaries:
        lines.append("nearby:")
        lines.extend(f"- {item}" for item in context.nearby_element_summaries)
    if context.footnotes:
        lines.append("footnotes:")
        lines.extend(f"- {item}" for item in context.footnotes)
    lines.append(DOCUMENT_CONTEXT_END)
    lines.append(TRUST_BOUNDARY_NOTICE)
    return "\n".join(lines)


def provenance_from_call(call: ModelCallMetadata) -> dict[str, JsonValue]:
    """Store model call metadata on the enriched element."""
    return {
        "provider": call.provider,
        "model_name": call.model_name,
        "role": call.role.value,
        "prompt_version": call.prompt_version,
        "latency_ms": call.latency_ms,
        "usage": (
            {
                "prompt_tokens": call.usage.prompt_tokens,
                "completion_tokens": call.usage.completion_tokens,
                "total_tokens": call.usage.total_tokens,
            }
            if call.usage
            else None
        ),
    }


def build_extraction_request(
    *,
    system_prompt: str,
    user_text: str,
    image_bytes: bytes | None = None,
    image_mime_type: str = "image/png",
    prompt_version: str,
    correlation_id: str | None = None,
) -> ExtractionRequest:
    """Build a structured extraction request with optional image part."""
    content: list[ContentPart] = [TextContentPart(text=user_text)]
    if image_bytes:
        content.append(
            ImageBytesContentPart(data=image_bytes, mime_type=image_mime_type)
        )
    return ExtractionRequest(
        messages=[
            ChatMessage(role=MessageRole.SYSTEM, content=system_prompt),
            ChatMessage(role=MessageRole.USER, content=content),
        ],
        role=ModelRole.EXTRACTION,
        prompt_version=prompt_version,
        correlation_id=correlation_id,
        metadata={"element_id": None},
    )


def element_text(element: DocumentElement) -> str:
    return element.normalized_content or element.raw_content or ""
