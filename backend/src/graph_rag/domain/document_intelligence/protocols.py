"""Repository port for custom Document Intelligence models.

Built-in models are static Python data (``application.document_intelligence
.catalog``), not rows here -- this repository only persists tenant-created
custom models.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from graph_rag.domain.document_intelligence.records import DocumentIntelligenceModelRecord
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
