"""Tenant and document repository adapters."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enterprise_rag.domain.ingestion.records import (
    DocumentRecord,
    DocumentVersionRecord,
    TenantRecord,
)
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.persistence.postgres.mappers import (
    document_to_record,
    tenant_to_record,
    version_to_record,
)
from enterprise_rag.infrastructure.persistence.postgres.models import (
    DocumentModel,
    DocumentVersionModel,
    TenantModel,
)
from enterprise_rag.infrastructure.persistence.postgres.rls import (
    require_matching_tenant,
    set_tenant_context,
)
from enterprise_rag.shared.exceptions import NotFoundError, TenantError, ValidationError


class SqlAlchemyTenantRepository:
    """SQLAlchemy implementation of ``TenantRepository``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, tenant: TenantRecord) -> TenantRecord:
        existing = await self._session.get(TenantModel, tenant.tenant_id)
        if existing is None:
            by_key = await self.get_by_key(tenant.tenant_key)
            if by_key is not None and by_key.tenant_id != tenant.tenant_id:
                raise ValidationError(
                    "tenant_key already exists for a different tenant_id",
                    details={"tenant_key": tenant.tenant_key},
                )
            model = TenantModel(
                tenant_id=tenant.tenant_id,
                tenant_key=tenant.tenant_key,
                display_name=tenant.display_name,
                is_active=tenant.is_active,
                metadata_json=dict(tenant.metadata),
            )
            self._session.add(model)
        else:
            existing.tenant_key = tenant.tenant_key
            existing.display_name = tenant.display_name
            existing.is_active = tenant.is_active
            existing.metadata_json = dict(tenant.metadata)
            model = existing
        await self._session.flush()
        return tenant_to_record(model)

    async def get_by_id(self, tenant_id: UUID) -> TenantRecord | None:
        model = await self._session.get(TenantModel, tenant_id)
        return tenant_to_record(model) if model is not None else None

    async def get_by_key(self, tenant_key: str) -> TenantRecord | None:
        result = await self._session.execute(
            select(TenantModel).where(TenantModel.tenant_key == tenant_key)
        )
        model = result.scalar_one_or_none()
        return tenant_to_record(model) if model is not None else None


class SqlAlchemyDocumentRepository:
    """SQLAlchemy implementation of ``DocumentRepository``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_document(
        self,
        tenant: TenantContext,
        document: DocumentRecord,
    ) -> DocumentRecord:
        require_matching_tenant(tenant, document.tenant_id)
        await set_tenant_context(self._session, tenant)
        model = DocumentModel(
            document_id=document.document_id,
            tenant_id=document.tenant_id,
            title=document.title,
            document_type=document.document_type,
            status=document.status.value,
            current_version_id=document.current_version_id,
            tags=list(document.tags),
            security_labels=list(document.security_labels),
            metadata_json=dict(document.metadata),
        )
        self._session.add(model)
        await self._session.flush()
        return document_to_record(model)

    async def get_document(
        self,
        tenant: TenantContext,
        document_id: UUID,
    ) -> DocumentRecord | None:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(DocumentModel).where(
                DocumentModel.document_id == document_id,
                DocumentModel.tenant_id == tenant.tenant_id,
            )
        )
        model = result.scalar_one_or_none()
        return document_to_record(model) if model is not None else None

    async def list_documents(
        self,
        tenant: TenantContext,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[DocumentRecord], int]:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        base = select(DocumentModel).where(DocumentModel.tenant_id == tenant.tenant_id)
        total_result = await self._session.execute(
            select(DocumentModel.document_id).where(
                DocumentModel.tenant_id == tenant.tenant_id
            )
        )
        total = len(list(total_result.scalars().all()))
        result = await self._session.execute(
            base.order_by(DocumentModel.updated_at.desc().nullslast()).offset(offset).limit(limit)
        )
        models = list(result.scalars().all())
        return [document_to_record(model) for model in models], total

    async def update_document(
        self,
        tenant: TenantContext,
        document: DocumentRecord,
    ) -> DocumentRecord:
        require_matching_tenant(tenant, document.tenant_id)
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(DocumentModel).where(
                DocumentModel.document_id == document.document_id,
                DocumentModel.tenant_id == tenant.tenant_id,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError(
                "Document not found",
                details={"document_id": str(document.document_id)},
            )
        model.title = document.title
        model.document_type = document.document_type
        model.status = document.status.value
        model.current_version_id = document.current_version_id
        model.tags = list(document.tags)
        model.security_labels = list(document.security_labels)
        model.metadata_json = dict(document.metadata)
        await self._session.flush()
        return document_to_record(model)

    async def create_version(
        self,
        tenant: TenantContext,
        version: DocumentVersionRecord,
    ) -> DocumentVersionRecord:
        require_matching_tenant(tenant, version.tenant_id)
        await set_tenant_context(self._session, tenant)
        document = await self.get_document(tenant, version.document_id)
        if document is None:
            raise NotFoundError(
                "Document not found for version",
                details={"document_id": str(version.document_id)},
            )
        model = DocumentVersionModel(
            version_id=version.version_id,
            tenant_id=version.tenant_id,
            document_id=version.document_id,
            version_number=version.version_number,
            source_filename=version.source_filename,
            mime_type=version.mime_type,
            content_hash=version.content_hash,
            byte_size=version.byte_size,
            page_count=version.page_count,
            original_object_key=version.original_object_key,
            status=version.status.value,
            metadata_json=dict(version.metadata),
        )
        self._session.add(model)
        await self._session.flush()
        return version_to_record(model)

    async def get_version(
        self,
        tenant: TenantContext,
        version_id: UUID,
    ) -> DocumentVersionRecord | None:
        tenant.ensure_authorized()
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(DocumentVersionModel).where(
                DocumentVersionModel.version_id == version_id,
                DocumentVersionModel.tenant_id == tenant.tenant_id,
            )
        )
        model = result.scalar_one_or_none()
        return version_to_record(model) if model is not None else None

    async def get_version_by_content_hash(
        self,
        tenant: TenantContext,
        document_id: UUID,
        content_hash: str,
    ) -> DocumentVersionRecord | None:
        tenant.ensure_authorized()
        if not content_hash:
            raise ValidationError("content_hash is required for duplicate detection")
        await set_tenant_context(self._session, tenant)
        result = await self._session.execute(
            select(DocumentVersionModel).where(
                DocumentVersionModel.tenant_id == tenant.tenant_id,
                DocumentVersionModel.document_id == document_id,
                DocumentVersionModel.content_hash == content_hash.lower(),
            )
        )
        model = result.scalar_one_or_none()
        return version_to_record(model) if model is not None else None


def assert_tenant_context_present(tenant: TenantContext | None) -> TenantContext:
    """Repository guard used by adapters that accept optional wiring mistakes."""
    if tenant is None:
        raise TenantError("Tenant context is required for tenant-owned operations")
    return tenant.ensure_authorized()
