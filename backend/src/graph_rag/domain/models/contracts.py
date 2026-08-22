"""Application-owned model request and response contracts.

No provider SDK types are exposed here.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.types import JsonValue


class ModelRole(StrEnum):
    """Configurable model roles."""

    TEXT = "text"
    VISION = "vision"
    EXTRACTION = "extraction"
    SUMMARIZATION = "summarization"
    QUERY = "query"
    ANSWER = "answer"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class MessageRole(StrEnum):
    """Chat message roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ContentPartType(StrEnum):
    """Multimodal content part kinds."""

    TEXT = "text"
    IMAGE_URL = "image_url"
    IMAGE_BYTES = "image_bytes"


class TextContentPart(BaseModel):
    """Plain text content part."""

    model_config = ConfigDict(extra="forbid")

    type: ContentPartType = ContentPartType.TEXT
    text: str


class ImageUrlContentPart(BaseModel):
    """Remote or data-URL image part."""

    model_config = ConfigDict(extra="forbid")

    type: ContentPartType = ContentPartType.IMAGE_URL
    url: str
    detail: str | None = None


class ImageBytesContentPart(BaseModel):
    """Inline image bytes part (adapters encode as needed)."""

    model_config = ConfigDict(extra="forbid")

    type: ContentPartType = ContentPartType.IMAGE_BYTES
    data: bytes
    mime_type: str = "image/png"
    detail: str | None = None


ContentPart = TextContentPart | ImageUrlContentPart | ImageBytesContentPart


class ChatMessage(BaseModel):
    """Provider-agnostic chat message."""

    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    content: str | list[ContentPart]


class TokenUsage(BaseModel):
    """Token accounting for a model call."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ModelCallMetadata(BaseModel):
    """Observability metadata for model invocations."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model_name: str
    role: ModelRole
    prompt_version: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    latency_ms: float | None = Field(default=None, ge=0.0)
    usage: TokenUsage | None = None
    extras: dict[str, JsonValue] = Field(default_factory=dict)


class GenerationRequest(BaseModel):
    """Chat / text generation request."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1)
    role: ModelRole = ModelRole.TEXT
    model_name: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=1)
    stop: list[str] | None = None
    correlation_id: str | None = None
    prompt_version: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class GenerationResponse(BaseModel):
    """Chat / text generation response."""

    model_config = ConfigDict(extra="forbid")

    text: str
    finish_reason: str | None = None
    call: ModelCallMetadata


class VisionRequest(BaseModel):
    """Vision understanding request."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1)
    role: ModelRole = ModelRole.VISION
    model_name: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=1)
    correlation_id: str | None = None
    prompt_version: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class VisionResponse(BaseModel):
    """Vision understanding response."""

    model_config = ConfigDict(extra="forbid")

    text: str
    finish_reason: str | None = None
    call: ModelCallMetadata


class ExtractionRequest(BaseModel):
    """Structured extraction request."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1)
    role: ModelRole = ModelRole.EXTRACTION
    model_name: str | None = None
    temperature: float | None = Field(default=0.0, ge=0.0, le=2.0)
    correlation_id: str | None = None
    prompt_version: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class EmbeddingRequest(BaseModel):
    """Embedding batch request."""

    model_config = ConfigDict(extra="forbid")

    texts: list[str] = Field(min_length=1)
    model_name: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class EmbeddingResponse(BaseModel):
    """Embedding vectors aligned with the request texts."""

    model_config = ConfigDict(extra="forbid")

    vectors: list[list[float]]
    call: ModelCallMetadata


class RerankItem(BaseModel):
    """Candidate document for reranking."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RerankRequest(BaseModel):
    """Rerank request over retrieval candidates."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    items: list[RerankItem] = Field(min_length=1)
    top_n: int | None = Field(default=None, ge=1)
    model_name: str | None = None
    correlation_id: str | None = None


class RerankResult(BaseModel):
    """Single reranked item."""

    model_config = ConfigDict(extra="forbid")

    id: str
    score: float
    index: int = Field(ge=0)


class RerankResponse(BaseModel):
    """Rerank response."""

    model_config = ConfigDict(extra="forbid")

    results: list[RerankResult]
    call: ModelCallMetadata


class TokenCountRequest(BaseModel):
    """Token counting request."""

    model_config = ConfigDict(extra="forbid")

    text: str
    model_name: str | None = None


class TokenCountResponse(BaseModel):
    """Token counting response."""

    model_config = ConfigDict(extra="forbid")

    token_count: int = Field(ge=0)
    model_name: str | None = None


class ModelUsageRecord(BaseModel):
    """Auditable model usage event for persistence."""

    model_config = ConfigDict(extra="forbid")

    usage_id: UUID
    tenant_id: UUID
    call: ModelCallMetadata
    document_id: UUID | None = None
    version_id: UUID | None = None
    ingestion_run_id: UUID | None = None
    stage: str | None = None
