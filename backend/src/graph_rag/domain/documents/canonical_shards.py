"""Sharded CanonicalDocument persistence contracts.

JSON shards are the authoritative parse artifacts. ``document.json`` holds
document metadata and page references only; per-page elements live in
``pages/NNNN.json``. Binary page renders and figure crops are stored beside
those JSON files and referenced by object key.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.documents.components import (
    DocumentAsset,
    DocumentSection,
    ElementReference,
    NormalizedPage,
    ParserInfo,
)
from graph_rag.domain.elements.models import DocumentElement
from graph_rag.domain.types import JsonValue

CANONICAL_SHARD_SCHEMA_VERSION = "canonical-shards-v1"


class PageArtifactRef(BaseModel):
    """Pointer to one page JSON shard (never contains elements)."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    object_key: str = Field(min_length=1)
    element_count: int = Field(default=0, ge=0)
    render_object_key: str | None = None


class AssetArtifactRef(BaseModel):
    """Pointer to a binary or table JSON asset stored beside the parse."""

    model_config = ConfigDict(extra="forbid")

    asset_id: UUID
    asset_type: str = Field(min_length=1)
    object_key: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    element_id: UUID | None = None
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)
    byte_size: int | None = Field(default=None, ge=0)


class CanonicalCurrentPointer(BaseModel):
    """``parse/current.json`` — which attempt is live for this version."""

    model_config = ConfigDict(extra="forbid")

    attempt_id: UUID
    manifest_key: str = Field(min_length=1)
    document_key: str = Field(min_length=1)


class CanonicalManifest(BaseModel):
    """Inventory of one parse attempt's shards and assets."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = CANONICAL_SHARD_SCHEMA_VERSION
    attempt_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    created_at: datetime
    parser_name: str | None = None
    page_count: int = Field(ge=0)
    document_key: str = Field(min_length=1)
    markdown_key: str = Field(min_length=1)
    pages: list[PageArtifactRef] = Field(default_factory=list)
    assets: list[AssetArtifactRef] = Field(default_factory=list)


class CanonicalDocumentMetadata(BaseModel):
    """Authoritative document.json: metadata + page refs, no elements."""

    model_config = ConfigDict(extra="forbid")

    attempt_id: UUID
    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    title: str | None = None
    source_filename: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    language: str | None = None
    page_count: int = Field(ge=0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    pages: list[NormalizedPage] = Field(default_factory=list)
    sections: list[DocumentSection] = Field(default_factory=list)
    assets: list[DocumentAsset] = Field(default_factory=list)
    references: list[ElementReference] = Field(default_factory=list)
    parser_info: ParserInfo
    page_refs: list[PageArtifactRef] = Field(default_factory=list)


class CanonicalPageArtifact(BaseModel):
    """One page's metadata, elements, and asset references."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    page: NormalizedPage
    elements: list[DocumentElement] = Field(default_factory=list)
    asset_refs: list[AssetArtifactRef] = Field(default_factory=list)
