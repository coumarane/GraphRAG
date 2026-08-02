"""API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.retrieval.enums import RetrievalMode
from enterprise_rag.domain.retrieval.models import (
    GraphPath,
    QueryResponse,
    RetrievedEvidence,
)
from enterprise_rag.domain.types import JsonValue


class IngestAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingestion_run_id: UUID
    document_id: UUID
    version_id: UUID
    status: str = "accepted"
    duplicate_version: bool = False


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    tenant_id: UUID
    title: str | None = None
    document_type: str | None = None
    status: str
    current_version_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)
    security_labels: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ElementItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: UUID
    document_id: UUID
    version_id: UUID
    element_type: str
    modality: Modality
    page_start: int
    page_end: int
    section_path: list[str] = Field(default_factory=list)
    preview: str = ""


class ElementListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ElementItem]
    total: int
    offset: int
    limit: int


class GraphViewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    nodes: list[dict[str, JsonValue]] = Field(default_factory=list)
    relationships: list[dict[str, JsonValue]] = Field(default_factory=list)


class DeletionAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: UUID
    document_id: UUID
    status: str = "accepted"
    vectors_deleted: int | None = None
    graph_deleted: int | None = None
    objects_deleted: int | None = None
    warnings: list[str] = Field(default_factory=list)


class StageProgressItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    status: str
    attempt_count: int = 0
    warning: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class IngestionRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingestion_run_id: UUID
    document_id: UUID
    version_id: UUID
    status: str
    parser_requested: str | None = None
    parser_used: str | None = None
    pages_processed: int = 0
    elements_processed: int = 0
    retry_count: int = 0
    latest_warning: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    correlation_id: str | None = None
    stages: list[StageProgressItem] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RetrievalSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    mode: RetrievalMode = RetrievalMode.AUTO
    document_ids: list[UUID] = Field(default_factory=list)
    modalities: list[Modality] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    security_labels: list[str] = Field(default_factory=list)
    top_k: int = Field(default=12, ge=1, le=100)
    graph_depth: int = Field(default=2, ge=0, le=10)
    include_graph_paths: bool = False
    rerank: bool = True


class RetrievalSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: RetrievalMode
    retrieval_trace_id: UUID
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    graph_paths: list[GraphPath] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QueryApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    mode: RetrievalMode = RetrievalMode.AUTO
    document_ids: list[UUID] = Field(default_factory=list)
    modalities: list[Modality] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    security_labels: list[str] = Field(default_factory=list)
    top_k: int = Field(default=12, ge=1, le=100)
    graph_depth: int = Field(default=2, ge=0, le=10)
    include_graph_paths: bool = False
    rerank: bool = True
    answer_model_override: str | None = None


class GraphSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(default_factory=list)
    query_terms: list[str] = Field(default_factory=list)
    depth: int = Field(default=2, ge=0, le=10)
    limit: int = Field(default=20, ge=1, le=100)
    include_claims: bool = True
    include_topics: bool = True


class GraphSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[dict[str, JsonValue]] = Field(default_factory=list)
    neighbors: list[dict[str, JsonValue]] = Field(default_factory=list)
    claims: list[dict[str, JsonValue]] = Field(default_factory=list)
    topics: list[dict[str, JsonValue]] = Field(default_factory=list)
    chunk_ids: list[UUID] = Field(default_factory=list)


class AssetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    url: str
    expires_seconds: int = 300


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


# Re-export QueryResponse for route typing convenience.
QueryApiResponse = QueryResponse
