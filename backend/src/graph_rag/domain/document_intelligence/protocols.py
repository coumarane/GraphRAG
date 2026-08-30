"""Repository port for custom Document Intelligence models.

Built-in models are static Python data (``application.document_intelligence
.catalog``), not rows here -- this repository only persists tenant-created
custom models.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from graph_rag.domain.document_intelligence.records import (
    DocumentExtractedFieldRecord,
    DocumentExtractionRunRecord,
    DocumentIntelligenceModelRecord,
)
from graph_rag.domain.tenant import TenantContext


class DocumentIntelligenceModelRepository(Protocol):
    """Custom Document Intelligence model port."""

    async def create_model(
        self,
        tenant: TenantContext,
        model: DocumentIntelligenceModelRecord,
    ) -> DocumentIntelligenceModelRecord:
        """Insert a custom model with its fields for the authorized tenant."""
        ...

    async def get_model(
        self,
        tenant: TenantContext,
        model_id: UUID,
    ) -> DocumentIntelligenceModelRecord | None:
        """Fetch a tenant-scoped custom model with its fields."""
        ...

    async def list_models(
        self,
        tenant: TenantContext,
    ) -> list[DocumentIntelligenceModelRecord]:
        """List the tenant's custom models with their fields."""
        ...


class DocumentExtractionRepository(Protocol):
    """Extraction run + extracted field port."""

    async def create_run(
        self,
        tenant: TenantContext,
        run: DocumentExtractionRunRecord,
    ) -> DocumentExtractionRunRecord:
        """Insert an extraction run row for the authorized tenant."""
        ...

    async def add_extracted_fields(
        self,
        tenant: TenantContext,
        run_id: UUID,
        fields: list[DocumentExtractedFieldRecord],
    ) -> list[DocumentExtractedFieldRecord]:
        """Insert extracted field rows for a run."""
        ...

    async def get_run(
        self,
        tenant: TenantContext,
        run_id: UUID,
    ) -> DocumentExtractionRunRecord | None:
        """Fetch a tenant-scoped extraction run."""
        ...

    async def list_fields_for_run(
        self,
        tenant: TenantContext,
        run_id: UUID,
    ) -> list[DocumentExtractedFieldRecord]:
        """List a run's extracted fields."""
        ...

    async def list_runs_for_version(
        self,
        tenant: TenantContext,
        document_id: UUID,
        version_id: UUID,
    ) -> list[DocumentExtractionRunRecord]:
        """List extraction runs for one document version, newest first."""
        ...
