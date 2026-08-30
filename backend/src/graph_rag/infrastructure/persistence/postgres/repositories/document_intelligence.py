"""Document Intelligence custom-model repository adapter."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graph_rag.domain.document_intelligence.records import (
    DocumentExtractedFieldRecord,
    DocumentExtractionRunRecord,
    DocumentIntelligenceModelRecord,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.postgres.mappers import (
    document_extracted_field_to_record,
    document_extraction_run_to_record,
    document_intelligence_model_to_record,
)
from graph_rag.infrastructure.persistence.postgres.models import (
    DocumentExtractedFieldModel,
    DocumentExtractionRunModel,
    DocumentIntelligenceModelFieldModel,
    DocumentIntelligenceModelModel,
)
from graph_rag.infrastructure.persistence.postgres.rls import (
    require_matching_tenant,
    set_tenant_context,
)
from graph_rag.shared.exceptions import ConflictError


class SqlAlchemyDocumentIntelligenceModelRepository:
    """SQLAlchemy implementation of ``DocumentIntelligenceModelRepository``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_model(
        self,
        tenant: TenantContext,
        model: DocumentIntelligenceModelRecord,
    ) -> DocumentIntelligenceModelRecord:
        require_matching_tenant(tenant, model.tenant_id)
        await set_tenant_context(self._session, tenant)
        existing = await self._session.get(DocumentIntelligenceModelModel, model.model_id)
        if existing is not None:
            raise ConflictError("Document Intelligence model already exists")
        row = DocumentIntelligenceModelModel(
            model_id=model.model_id,
            tenant_id=model.tenant_id,
            model_key=model.model_key,
            name=model.name,
            model_type=model.model_type,
            version=model.version,
            provider=model.provider,
            is_builtin=model.is_builtin,
            created_by_user_id=model.created_by_user_id,
            metadata_json=(
                {"field_entity_mappings": model.field_entity_mappings}
                if model.field_entity_mappings
                else {}
            ),
        )
        self._session.add(row)
        field_rows = [
            DocumentIntelligenceModelFieldModel(
                field_id=field.field_id,
                tenant_id=field.tenant_id,
                model_id=field.model_id,
                name=field.name,
                label=field.label,
                field_type=field.field_type,
                default_selected=field.default_selected,
                promote_to_document_metadata=field.promote_to_document_metadata,
                sort_order=field.sort_order,
            )
            for field in model.fields
        ]
        for field_row in field_rows:
            self._session.add(field_row)
        await self._session.flush()
        return document_intelligence_model_to_record(row, field_rows)

    async def get_model(
        self,
        tenant: TenantContext,
        model_id: UUID,
    ) -> DocumentIntelligenceModelRecord | None:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(DocumentIntelligenceModelModel)
            .where(
                DocumentIntelligenceModelModel.model_id == model_id,
                DocumentIntelligenceModelModel.tenant_id == tenant.tenant_id,
            )
            .execution_options(populate_existing=True)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        fields = await self._list_fields(model_id)
        return document_intelligence_model_to_record(row, fields)

    async def list_models(
        self,
        tenant: TenantContext,
    ) -> list[DocumentIntelligenceModelRecord]:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(DocumentIntelligenceModelModel)
            .where(DocumentIntelligenceModelModel.tenant_id == tenant.tenant_id)
            .order_by(DocumentIntelligenceModelModel.created_at.desc().nullslast())
            .execution_options(populate_existing=True)
        )
        rows = list(result.scalars().all())
        records = []
        for row in rows:
            fields = await self._list_fields(row.model_id)
            records.append(document_intelligence_model_to_record(row, fields))
        return records

    async def _list_fields(
        self,
        model_id: UUID,
    ) -> list[DocumentIntelligenceModelFieldModel]:
        result = await self._session.execute(
            select(DocumentIntelligenceModelFieldModel)
            .where(DocumentIntelligenceModelFieldModel.model_id == model_id)
            .order_by(DocumentIntelligenceModelFieldModel.sort_order.asc())
        )
        return list(result.scalars().all())


class SqlAlchemyDocumentExtractionRepository:
    """SQLAlchemy implementation of ``DocumentExtractionRepository``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(
        self,
        tenant: TenantContext,
        run: DocumentExtractionRunRecord,
    ) -> DocumentExtractionRunRecord:
        require_matching_tenant(tenant, run.tenant_id)
        await set_tenant_context(self._session, tenant)
        existing = await self._session.get(DocumentExtractionRunModel, run.run_id)
        if existing is not None:
            raise ConflictError("Document extraction run already exists")
        row = DocumentExtractionRunModel(
            run_id=run.run_id,
            tenant_id=run.tenant_id,
            document_id=run.document_id,
            version_id=run.version_id,
            ingestion_run_id=run.ingestion_run_id,
            model_id=run.model_id,
            model_key=run.model_key,
            provider=run.provider,
            plugin_version=run.plugin_version,
            status=run.status,
            fingerprint=run.fingerprint,
            selected_fields_json=list(run.selected_fields),
            error_code=run.error_code,
            error_message=run.error_message,
        )
        self._session.add(row)
        await self._session.flush()
        return document_extraction_run_to_record(row)

    async def add_extracted_fields(
        self,
        tenant: TenantContext,
        run_id: UUID,
        fields: list[DocumentExtractedFieldRecord],
    ) -> list[DocumentExtractedFieldRecord]:
        await set_tenant_context(self._session, tenant)
        rows = []
        for field in fields:
            require_matching_tenant(tenant, field.tenant_id)
            row = DocumentExtractedFieldModel(
                extracted_field_id=field.extracted_field_id,
                tenant_id=field.tenant_id,
                run_id=run_id,
                name=field.name,
                value_json=field.value,
                normalized_value_json=field.normalized_value,
                confidence=field.confidence,
                confidence_band=field.confidence_band,
                page=field.page,
                source_text=field.source_text,
                bounding_box_json=field.bounding_box,
                extraction_method=field.extraction_method,
                model_name=field.model_name,
            )
            self._session.add(row)
            rows.append(row)
        await self._session.flush()
        return [document_extracted_field_to_record(row) for row in rows]

    async def get_run(
        self,
        tenant: TenantContext,
        run_id: UUID,
    ) -> DocumentExtractionRunRecord | None:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(DocumentExtractionRunModel)
            .where(
                DocumentExtractionRunModel.run_id == run_id,
                DocumentExtractionRunModel.tenant_id == tenant.tenant_id,
            )
            .execution_options(populate_existing=True)
        )
        row = result.scalar_one_or_none()
        return document_extraction_run_to_record(row) if row is not None else None

    async def list_fields_for_run(
        self,
        tenant: TenantContext,
        run_id: UUID,
    ) -> list[DocumentExtractedFieldRecord]:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(DocumentExtractedFieldModel)
            .where(
                DocumentExtractedFieldModel.run_id == run_id,
                DocumentExtractedFieldModel.tenant_id == tenant.tenant_id,
            )
            .order_by(DocumentExtractedFieldModel.name.asc())
        )
        return [document_extracted_field_to_record(row) for row in result.scalars().all()]

    async def list_runs_for_version(
        self,
        tenant: TenantContext,
        document_id: UUID,
        version_id: UUID,
    ) -> list[DocumentExtractionRunRecord]:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(DocumentExtractionRunModel)
            .where(
                DocumentExtractionRunModel.tenant_id == tenant.tenant_id,
                DocumentExtractionRunModel.document_id == document_id,
                DocumentExtractionRunModel.version_id == version_id,
            )
            .order_by(DocumentExtractionRunModel.created_at.desc().nullslast())
            .execution_options(populate_existing=True)
        )
        return [document_extraction_run_to_record(row) for row in result.scalars().all()]
