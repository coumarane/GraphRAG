"""Normalized multimodal document aggregate."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from graph_rag.domain.documents.components import (
    DocumentAsset,
    DocumentSection,
    ElementReference,
    NormalizedPage,
    ParserInfo,
)
from graph_rag.domain.elements.models import DocumentElement
from graph_rag.domain.types import JsonValue

_ELEMENT_ADAPTER: TypeAdapter[DocumentElement] = TypeAdapter(DocumentElement)


class NormalizedDocument(BaseModel):
    """Application-owned normalized multimodal document.

    Matches ``contracts/normalized-document.schema.yaml``.
    """

    model_config = ConfigDict(extra="forbid")

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
    elements: list[DocumentElement] = Field(default_factory=list)
    sections: list[DocumentSection] = Field(default_factory=list)
    assets: list[DocumentAsset] = Field(default_factory=list)
    references: list[ElementReference] = Field(default_factory=list)
    parser_info: ParserInfo

    @model_validator(mode="after")
    def _validate_consistency(self) -> NormalizedDocument:
        if self.page_count and self.pages and len(self.pages) != self.page_count:
            msg = "page_count must equal the number of pages when pages are provided"
            raise ValueError(msg)

        element_ids = [element.element_id for element in self.elements]
        if len(element_ids) != len(set(element_ids)):
            msg = "element_id values must be unique within a document"
            raise ValueError(msg)

        for element in self.elements:
            if element.tenant_id != self.tenant_id:
                msg = "element tenant_id must match document tenant_id"
                raise ValueError(msg)
            if element.document_id != self.document_id:
                msg = "element document_id must match document document_id"
                raise ValueError(msg)
            if element.version_id != self.version_id:
                msg = "element version_id must match document version_id"
                raise ValueError(msg)
            if self.page_count and element.page_end > self.page_count:
                msg = "element page_end exceeds document page_count"
                raise ValueError(msg)
        return self

    @classmethod
    def parse_element(cls, data: object) -> DocumentElement:
        """Parse a single discriminated element payload."""
        return _ELEMENT_ADAPTER.validate_python(data)
