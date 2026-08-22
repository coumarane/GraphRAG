"""Citation contracts for grounded answers."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from graph_rag.domain.modality import Modality


class Citation(BaseModel):
    """Validated source citation derived only from retrieved evidence.

    Field set is a superset of ``contracts/query-response.schema.yaml`` citation
    items; ``tenant_id`` is required by the domain model for isolation checks.
    """

    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(min_length=1)
    tenant_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_name: str = Field(min_length=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    section_path: list[str] = Field(default_factory=list)
    element_id: UUID | None = None
    chunk_id: UUID
    modality: Modality
    source_object_key: str = Field(min_length=1)
    evidence: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def _validate_page_range(self) -> Citation:
        if self.page_end < self.page_start:
            msg = "page_end must be greater than or equal to page_start"
            raise ValueError(msg)
        return self
