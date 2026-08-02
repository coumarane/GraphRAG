"""Retrieval request/result and query response contracts."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.domain.citations.models import Citation
from enterprise_rag.domain.modality import Modality
from enterprise_rag.domain.retrieval.enums import RetrievalMode
from enterprise_rag.domain.types import JsonValue


class RetrievalFilters(BaseModel):
    """Tenant-safe retrieval constraints."""

    model_config = ConfigDict(extra="forbid")

    document_ids: list[UUID] = Field(default_factory=list)
    modalities: list[Modality] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    security_labels: list[str] = Field(default_factory=list)


class RetrievalRequest(BaseModel):
    """Evidence search request without answer generation."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    mode: RetrievalMode = RetrievalMode.AUTO
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    top_k: int = Field(default=12, ge=1, le=100)
    graph_depth: int = Field(default=2, ge=0, le=10)
    include_graph_paths: bool = False
    rerank: bool = True


class QueryRequest(BaseModel):
    """Grounded answer request."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    mode: RetrievalMode = RetrievalMode.AUTO
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    top_k: int = Field(default=12, ge=1, le=100)
    graph_depth: int = Field(default=2, ge=0, le=10)
    include_graph_paths: bool = False
    rerank: bool = True
    answer_model_override: str | None = None


class GraphPath(BaseModel):
    """Optional supporting graph path returned with an answer."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    supporting_citations: list[str] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RetrievedEvidence(BaseModel):
    """Single evidence item prior to answer generation."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_name: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    section_path: list[str] = Field(default_factory=list)
    element_id: UUID | None = None
    modality: Modality
    source_object_key: str
    text: str
    score: float | None = None
    score_components: dict[str, float] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    """Fused retrieval evidence bundle."""

    model_config = ConfigDict(extra="forbid")

    mode: RetrievalMode
    retrieval_trace_id: UUID
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    graph_paths: list[GraphPath] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    """Grounded answer contract matching ``contracts/query-response.schema.yaml``."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    retrieval_mode: RetrievalMode
    citations: list[Citation] = Field(default_factory=list)
    retrieval_trace_id: UUID
    warnings: list[str] = Field(default_factory=list)
    graph_paths: list[GraphPath] = Field(default_factory=list)
