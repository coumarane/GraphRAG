"""In-memory Document Intelligence repositories for local mode/tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel

from graph_rag.domain.document_intelligence.records import (
    DocumentExtractedFieldRecord,
    DocumentExtractionRunRecord,
    DocumentIntelligenceModelRecord,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import AuthorizationError, ConflictError


def _stamped[T: BaseModel](record: T) -> T:
    """Mirror Postgres's server_default=func.now() so in-memory ordering matches."""
    created_at = getattr(record, "created_at", None)
    updated_at = getattr(record, "updated_at", None)
    if created_at is not None and updated_at is not None:
        return record
    now = datetime.now(UTC)
    return record.model_copy(
        update={
            "created_at": created_at or now,
            "updated_at": updated_at or now,
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


class InMemoryDocumentExtractionRepository:
    """Extraction run/field store for local mode."""

    def __init__(self) -> None:
        self.runs: dict[tuple[UUID, UUID], DocumentExtractionRunRecord] = {}
        self.fields: dict[UUID, list[DocumentExtractedFieldRecord]] = {}

    @staticmethod
    def _assert_tenant(tenant: TenantContext, owner: UUID) -> None:
        if tenant.tenant_id != owner:
            raise AuthorizationError("Document extraction run tenant mismatch")

    async def create_run(
        self,
        tenant: TenantContext,
        run: DocumentExtractionRunRecord,
    ) -> DocumentExtractionRunRecord:
        self._assert_tenant(tenant, run.tenant_id)
        key = (tenant.tenant_id, run.run_id)
        if key in self.runs:
            raise ConflictError("Document extraction run already exists")
        record = _stamped(run)
        self.runs[key] = record
        self.fields.setdefault(run.run_id, [])
        return record

    async def add_extracted_fields(
        self,
        tenant: TenantContext,
        run_id: UUID,
        fields: list[DocumentExtractedFieldRecord],
    ) -> list[DocumentExtractedFieldRecord]:
        for field in fields:
            self._assert_tenant(tenant, field.tenant_id)
        stamped = [_stamped(field) for field in fields]
        self.fields.setdefault(run_id, []).extend(stamped)
        return stamped

    async def get_run(
        self,
        tenant: TenantContext,
        run_id: UUID,
    ) -> DocumentExtractionRunRecord | None:
        return self.runs.get((tenant.tenant_id, run_id))

    async def list_fields_for_run(
        self,
        tenant: TenantContext,
        run_id: UUID,
    ) -> list[DocumentExtractedFieldRecord]:
        if (tenant.tenant_id, run_id) not in self.runs:
            return []
        return list(self.fields.get(run_id, []))

    async def list_runs_for_version(
        self,
        tenant: TenantContext,
        document_id: UUID,
        version_id: UUID,
    ) -> list[DocumentExtractionRunRecord]:
        items = [
            run
            for (owner, _run_id), run in self.runs.items()
            if owner == tenant.tenant_id
            and run.document_id == document_id
            and run.version_id == version_id
        ]
        items.sort(key=lambda item: item.created_at or item.run_id.hex, reverse=True)
        return items
