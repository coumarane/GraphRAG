"""Tenant-scoped upload session repository."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graph_rag.domain.ingestion.upload_session import UploadSessionRecord, UploadSessionStatus
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.postgres.models.uploads import UploadSessionModel
from graph_rag.infrastructure.persistence.postgres.rls import (
    require_matching_tenant,
    set_tenant_context,
)
from graph_rag.shared.exceptions import NotFoundError


def _to_record(model: UploadSessionModel) -> UploadSessionRecord:
    return UploadSessionRecord(
        upload_id=model.upload_id,
        tenant_id=model.tenant_id,
        user_id=model.user_id,
        document_id=model.document_id,
        version_id=model.version_id,
        staging_object_key=model.staging_object_key,
        final_object_key=model.final_object_key,
        source_filename=model.source_filename,
        title=model.title,
        declared_byte_size=int(model.declared_byte_size),
        actual_byte_size=None if model.actual_byte_size is None else int(model.actual_byte_size),
        content_hash=model.content_hash,
        etag=model.etag,
        object_version_id=model.object_version_id,
        mime_type=model.mime_type,
        status=UploadSessionStatus(model.status),
        expires_at=model.expires_at,
        ingestion_run_id=model.ingestion_run_id,
        source_url=model.source_url,
        document_reservation_id=model.document_reservation_id,
        storage_reservation_id=model.storage_reservation_id,
        error_code=model.error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyUploadSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: UploadSessionRecord) -> UploadSessionRecord:
        model = UploadSessionModel(
            upload_id=record.upload_id,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            document_id=record.document_id,
            version_id=record.version_id,
            staging_object_key=record.staging_object_key,
            final_object_key=record.final_object_key,
            source_filename=record.source_filename,
            title=record.title,
            declared_byte_size=record.declared_byte_size,
            actual_byte_size=record.actual_byte_size,
            content_hash=record.content_hash,
            etag=record.etag,
            object_version_id=record.object_version_id,
            mime_type=record.mime_type,
            status=record.status.value,
            expires_at=record.expires_at,
            ingestion_run_id=record.ingestion_run_id,
            source_url=record.source_url,
            document_reservation_id=record.document_reservation_id,
            storage_reservation_id=record.storage_reservation_id,
            error_code=record.error_code,
        )
        self._session.add(model)
        await self._session.flush()
        return _to_record(model)

    async def get(self, tenant: TenantContext, upload_id: UUID) -> UploadSessionRecord | None:
        await set_tenant_context(self._session, tenant)
        model = await self._session.get(UploadSessionModel, upload_id)
        if model is None:
            return None
        require_matching_tenant(tenant, model.tenant_id)
        return _to_record(model)

    async def save(self, record: UploadSessionRecord) -> UploadSessionRecord:
        model = await self._session.get(UploadSessionModel, record.upload_id)
        if model is None:
            raise NotFoundError(
                "Upload session not found",
                details={"upload_id": str(record.upload_id)},
            )
        model.expires_at = record.expires_at
        model.status = record.status.value
        model.document_id = record.document_id
        model.version_id = record.version_id
        model.staging_object_key = record.staging_object_key
        model.final_object_key = record.final_object_key
        model.title = record.title
        model.actual_byte_size = record.actual_byte_size
        model.content_hash = record.content_hash
        model.etag = record.etag
        model.object_version_id = record.object_version_id
        model.mime_type = record.mime_type
        model.status = record.status.value
        model.ingestion_run_id = record.ingestion_run_id
        model.error_code = record.error_code
        await self._session.flush()
        return _to_record(model)

    async def list_pending_expired(self, now: datetime) -> list[UploadSessionRecord]:
        stmt = select(UploadSessionModel).where(
            UploadSessionModel.status == UploadSessionStatus.PENDING.value,
            UploadSessionModel.expires_at <= now,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_record(row) for row in rows]
