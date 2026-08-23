"""In-memory Document Intelligence custom-model repository for local mode/tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from graph_rag.domain.document_intelligence.records import DocumentIntelligenceModelRecord
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import AuthorizationError, ConflictError


def _stamped(record: DocumentIntelligenceModelRecord) -> DocumentIntelligenceModelRecord:
    """Mirror Postgres's server_default=func.now() so in-memory ordering matches."""
    if record.created_at is not None and record.updated_at is not None:
        return record
    now = datetime.now(UTC)
    return record.model_copy(
        update={
            "created_at": record.created_at or now,
            "updated_at": record.updated_at or now,
        }
    )


class InMemoryDocumentIntelligenceModelRepository:
    """Custom model store for local mode."""

    def __init__(self) -> None:
        self.models: dict[tuple[UUID, UUID], DocumentIntelligenceModelRecord] = {}

    @staticmethod
    def _assert_tenant(tenant: TenantContext, owner: UUID) -> None:
        if tenant.tenant_id != owner:
            raise AuthorizationError("Document Intelligence model tenant mismatch")

    async def create_model(
        self,
        tenant: TenantContext,
        model: DocumentIntelligenceModelRecord,
    ) -> DocumentIntelligenceModelRecord:
        self._assert_tenant(tenant, model.tenant_id)
        key = (tenant.tenant_id, model.model_id)
        if key in self.models:
            raise ConflictError("Document Intelligence model already exists")
        record = _stamped(model)
        self.models[key] = record
        return record

    async def get_model(
        self,
        tenant: TenantContext,
        model_id: UUID,
    ) -> DocumentIntelligenceModelRecord | None:
        return self.models.get((tenant.tenant_id, model_id))

    async def list_models(
        self,
        tenant: TenantContext,
    ) -> list[DocumentIntelligenceModelRecord]:
        items = [
            model for (owner, _model_id), model in self.models.items() if owner == tenant.tenant_id
        ]
        items.sort(key=lambda item: item.created_at or item.model_id.hex)
        return items
