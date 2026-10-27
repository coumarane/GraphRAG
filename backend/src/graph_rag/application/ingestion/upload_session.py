"""Create, complete, and expire direct-upload sessions."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from graph_rag.application.ingestion.enqueue import enqueue_ingest_ids
from graph_rag.application.ingestion.register_source import _title_from_source
from graph_rag.application.ingestion.verify_object import VerifiedObject, verify_object_stream
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.protocols import (
    DocumentRepository,
    IngestionRepository,
    TenantRepository,
)
from graph_rag.domain.ingestion.records import (
    DocumentRecord,
    DocumentVersionRecord,
    IngestionRunRecord,
    TenantRecord,
)
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus, IngestionRunStatus
from graph_rag.domain.ingestion.state_machine import build_persisted_stage_records
from graph_rag.domain.ingestion.upload_session import UploadSessionRecord, UploadSessionStatus
from graph_rag.domain.quotas.models import QuotaMetric, QuotaReservation
from graph_rag.domain.storage.limits import assert_safe_zip_archive
from graph_rag.domain.storage.object_keys import (
    original_object_key,
    sanitize_filename,
    staging_object_key,
)
from graph_rag.domain.storage.protocols import ObjectStore
from graph_rag.domain.tenant import TenantContext
from graph_rag.domain.types import JsonValue
from graph_rag.infrastructure.intake.mime_detection import detect_mime_type
from graph_rag.infrastructure.observability.metrics import get_metrics
from graph_rag.shared.exceptions import (
    ConflictError,
    NotFoundError,
    UnsupportedDocumentError,
    ValidationError,
)
from graph_rag.shared.logging import get_logger

logger = get_logger(__name__)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value

MAX_UPLOAD_BYTES = 104_857_600
WRITE_URL_SECONDS = 900


@dataclass
class UploadAccepted:
    upload_id: UUID
    expires_at: datetime
    upload_url: str | None
    method: str | None


@dataclass
class UploadCompleted:
    ingestion_run_id: UUID
    document_id: UUID
    version_id: UUID
    status: str = "accepted"
    duplicate_version: bool = False


class UploadSessionService:
    """Acceptance is one document, one final object, and one outbox row."""

    def __init__(
        self,
        *,
        sessions: object,
        tenant_repo: TenantRepository,
        document_repo: DocumentRepository,
        ingestion_repo: IngestionRepository,
        object_store: ObjectStore,
        quotas: object | None = None,
        outbox: object | None = None,
        authorization: object | None = None,
        source_loader: object | None = None,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
        config_fingerprint: str = "intake-v1",
    ) -> None:
        self._sessions = sessions
        self._tenants = tenant_repo
        self._documents = document_repo
        self._ingestion = ingestion_repo
        self._objects = object_store
        self._quotas = quotas
        self._outbox = outbox
        self._authorization = authorization
        self._source_loader = source_loader
        self._max_bytes = max_upload_bytes
        self._fingerprint = config_fingerprint
        self._locks: dict[UUID, asyncio.Lock] = {}

    async def create(
        self,
        tenant: TenantContext,
        *,
        filename: str,
        byte_size: int | None,
        title: str | None = None,
        source_url: str | None = None,
    ) -> UploadAccepted:
        tenant.ensure_authorized()
        await self._authorize(tenant)
        safe_name = sanitize_filename(filename)
        if source_url:
            if byte_size is not None and (byte_size < 1 or byte_size > self._max_bytes):
                raise ValidationError(
                    "Declared size is outside the published limit",
                    details={"byte_size": byte_size},
                )
            declared = byte_size or self._max_bytes
        else:
            if byte_size is None or byte_size < 1 or byte_size > self._max_bytes:
                raise ValidationError(
                    "Declared size is outside the published limit",
                    details={"byte_size": byte_size},
                )
            declared = byte_size
        upload_id = new_id()
        doc_reservation = await self._quota(tenant, QuotaMetric.DOCUMENTS, 1)
        storage_reservation = await self._quota(tenant, QuotaMetric.STORAGE_BYTES, declared)
        expires_at = datetime.now(UTC) + timedelta(seconds=WRITE_URL_SECONDS)
        staging = None
        upload_url = None
        try:
            if source_url is None:
                staging = staging_object_key(
                    tenant_id=tenant.tenant_id,
                    upload_id=upload_id,
                    filename=safe_name,
                )
                await self._objects.ensure_bucket()
                upload_url = await self._objects.presign_put(
                    tenant,
                    object_key=staging,
                    expires_seconds=WRITE_URL_SECONDS,
                )
            record = UploadSessionRecord(
                upload_id=upload_id,
                tenant_id=tenant.tenant_id,
                user_id=tenant.user_id,
                staging_object_key=staging,
                source_filename=safe_name,
                title=(title or "").strip() or None,
                declared_byte_size=declared,
                expires_at=expires_at,
                source_url=source_url,
                document_reservation_id=None
                if doc_reservation is None
                else doc_reservation.reservation_id,
                storage_reservation_id=None
                if storage_reservation is None
                else storage_reservation.reservation_id,
            )
            await self._sessions.add(record)  # type: ignore[attr-defined]
        except Exception:
            await self._release(doc_reservation)
            await self._release(storage_reservation)
            raise
        get_metrics().incr("upload_sessions_created_total")
        logger.info(
            "upload_session_created",
            tenant_id=str(tenant.tenant_id),
            upload_id=str(upload_id),
            user_id=None if tenant.user_id is None else str(tenant.user_id),
        )
        return UploadAccepted(
            upload_id=upload_id,
            expires_at=expires_at,
            upload_url=upload_url,
            method=None if upload_url is None else "PUT",
        )

    async def complete(
        self,
        tenant: TenantContext,
        upload_id: UUID,
        *,
        title: str | None = None,
    ) -> UploadCompleted:
        tenant.ensure_authorized()
        await self._authorize(tenant)
        lock = self._locks.setdefault(upload_id, asyncio.Lock())
        async with lock:
            record = await self._sessions.get(tenant, upload_id)  # type: ignore[attr-defined]
            if record is None:
                raise NotFoundError(
                    "Upload session not found",
                    details={"upload_id": str(upload_id)},
                )
            if (
                record.status is UploadSessionStatus.COMPLETED
                and record.document_id
                and record.ingestion_run_id
            ):
                return UploadCompleted(
                    ingestion_run_id=record.ingestion_run_id,
                    document_id=record.document_id,
                    version_id=record.version_id or record.document_id,
                )
            if record.status in {UploadSessionStatus.EXPIRED, UploadSessionStatus.REJECTED}:
                raise ConflictError(
                    "Upload session is no longer acceptable",
                    details={"upload_id": str(upload_id), "status": record.status.value},
                )
            if _aware(record.expires_at) <= datetime.now(UTC):
                await self._expire_record(tenant, record)
                raise ConflictError("Upload session expired", details={"upload_id": str(upload_id)})
            try:
                verified, final_key, etag, version_id_obj = await self._accept_bytes(tenant, record)
            except NotFoundError as exc:
                await self._reject(tenant, record, code="missing_object")
                raise ValidationError("Upload bytes were not stored", details=exc.details) from exc
            except (ValidationError, ConflictError, UnsupportedDocumentError) as exc:
                await self._reject(tenant, record, code=getattr(exc, "code", "rejected"))
                raise
            return await self._commit_document(
                tenant,
                record,
                verified=verified,
                final_key=final_key,
                etag=etag,
                object_version_id=version_id_obj,
                title=title if title is not None else record.title,
            )

    async def expire_due(self, now: datetime | None = None) -> int:
        stamp = now or datetime.now(UTC)
        pending = await self._sessions.list_pending_expired(stamp)  # type: ignore[attr-defined]
        count = 0
        for record in pending:
            tenant = TenantContext(tenant_id=record.tenant_id, user_id=record.user_id)
            await self._expire_record(tenant, record)
            count += 1
        return count

    async def _accept_bytes(
        self,
        tenant: TenantContext,
        record: UploadSessionRecord,
    ) -> tuple[VerifiedObject, str, str | None, str | None]:
        document_id = new_id()
        version_id = new_id()
        final_key = original_object_key(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            filename=record.source_filename,
        )
        if record.source_url:
            if self._source_loader is None:
                raise ValidationError("Remote intake is not configured")
            loaded = await self._source_loader.load_url(record.source_url)  # type: ignore[attr-defined]
            data = loaded.content
            if len(data) < 1 or len(data) > record.declared_byte_size:
                raise ValidationError(
                    "Remote object is outside the published limit",
                    details={"byte_size": len(data)},
                )
            if data.startswith(b"PK"):
                assert_safe_zip_archive(data)
            mime_type = detect_mime_type(data, filename=record.source_filename)
            from graph_rag.domain.ids import content_sha256_hex

            content_hash = content_sha256_hex(data)
            stored = await self._objects.put_bytes(
                tenant,
                object_key=final_key,
                data=data,
                content_type=mime_type,
                content_hash=content_hash,
            )
            await self._objects.lock_object(tenant, object_key=final_key)
            head = await self._objects.head_object(tenant, object_key=final_key)
            if head.byte_size != len(data) or (
                stored.etag and head.etag and head.etag != stored.etag
            ):
                raise ValidationError("Stored object does not match the accepted bytes")
            record.document_id = document_id
            record.version_id = version_id
            record.final_object_key = final_key
            return (
                VerifiedObject(content_hash=content_hash, byte_size=len(data), mime_type=mime_type),
                final_key,
                stored.etag,
                head.version_id,
            )
        if record.staging_object_key is None:
            raise ValidationError("Upload session has no staging object")
        verified = await verify_object_stream(
            self._objects,
            tenant,
            object_key=record.staging_object_key,
            declared_byte_size=record.declared_byte_size,
            filename=record.source_filename,
            max_bytes=self._max_bytes,
        )
        stored = await self._objects.copy_object(
            tenant,
            source_key=record.staging_object_key,
            dest_key=final_key,
            content_type=verified.mime_type,
            content_hash=verified.content_hash,
        )
        head = await self._objects.head_object(tenant, object_key=final_key)
        if head.byte_size != verified.byte_size or (
            stored.etag and head.etag and head.etag != stored.etag
        ):
            await self._objects.delete_object(tenant, object_key=final_key)
            raise ValidationError("Final object does not match the staged bytes")
        await self._objects.lock_object(tenant, object_key=final_key)
        await self._objects.delete_object(tenant, object_key=record.staging_object_key)
        record.document_id = document_id
        record.version_id = version_id
        record.final_object_key = final_key
        return verified, final_key, stored.etag or head.etag, head.version_id

    async def _commit_document(
        self,
        tenant: TenantContext,
        record: UploadSessionRecord,
        *,
        verified: VerifiedObject,
        final_key: str,
        etag: str | None,
        object_version_id: str | None,
        title: str | None,
    ) -> UploadCompleted:
        await self._ensure_tenant(tenant)
        await self._documents.lock_for_content_hash(tenant, verified.content_hash)
        duplicate = await self._documents.get_version_by_content_hash(
            tenant, None, verified.content_hash
        )
        if duplicate is not None:
            owner = await self._documents.get_document(tenant, duplicate.document_id)
            if owner is not None and owner.status is not DocumentLifecycleStatus.DELETED:
                await self._reject(tenant, record, code="duplicate")
                raise ConflictError(
                    "This document is already uploaded. Identical content was found.",
                    details={
                        "document_id": str(duplicate.document_id),
                        "version_id": str(duplicate.version_id),
                    },
                )
        assert record.document_id is not None and record.version_id is not None
        display = _title_from_source(
            source_filename=record.source_filename,
            request_title=title,
            loaded_filename=record.source_filename,
        )
        document = await self._documents.create_document(
            tenant,
            DocumentRecord(
                document_id=record.document_id,
                tenant_id=tenant.tenant_id,
                title=display,
                status=DocumentLifecycleStatus.INGESTING,
                owner_user_id=tenant.user_id,
            ),
        )
        version = await self._documents.create_version(
            tenant,
            DocumentVersionRecord(
                version_id=record.version_id,
                tenant_id=tenant.tenant_id,
                document_id=document.document_id,
                version_number=1,
                source_filename=record.source_filename,
                mime_type=verified.mime_type,
                content_hash=verified.content_hash,
                byte_size=verified.byte_size,
                original_object_key=final_key,
                etag=etag,
                object_version_id=object_version_id,
                status=DocumentLifecycleStatus.INGESTING,
            ),
        )
        document.current_version_id = version.version_id
        document.title = display
        await self._documents.update_document(tenant, document)
        run_id = new_id()
        stages = build_persisted_stage_records(
            tenant_id=tenant.tenant_id,
            ingestion_run_id=run_id,
        )
        metadata: dict[str, JsonValue] = {}
        if record.source_url:
            metadata["source_url"] = record.source_url
        run = await self._ingestion.create_run(
            tenant,
            IngestionRunRecord(
                ingestion_run_id=run_id,
                tenant_id=tenant.tenant_id,
                document_id=document.document_id,
                version_id=version.version_id,
                status=IngestionRunStatus.PENDING,
                parser_requested="auto",
                config_fingerprint=self._fingerprint,
                content_hash=verified.content_hash,
                metadata=metadata,
            ),
            stages,
        )
        if self._outbox is not None:
            await enqueue_ingest_ids(
                self._outbox,
                tenant=tenant,
                ingestion_run_id=run.ingestion_run_id,
                document_id=document.document_id,
                version_id=version.version_id,
                content_hash=verified.content_hash,
                config_fingerprint=self._fingerprint,
                correlation_id=None,
            )
        await self._commit_quota(record.document_reservation_id, 1)
        await self._commit_quota(record.storage_reservation_id, verified.byte_size)
        record.status = UploadSessionStatus.COMPLETED
        record.final_object_key = final_key
        record.actual_byte_size = verified.byte_size
        record.content_hash = verified.content_hash
        record.etag = etag
        record.object_version_id = object_version_id
        record.mime_type = verified.mime_type
        record.ingestion_run_id = run.ingestion_run_id
        record.title = display
        await self._sessions.save(record)  # type: ignore[attr-defined]
        get_metrics().incr("upload_sessions_completed_total")
        logger.info(
            "upload_session_completed",
            tenant_id=str(tenant.tenant_id),
            upload_id=str(record.upload_id),
            run_id=str(run.ingestion_run_id),
        )
        return UploadCompleted(
            ingestion_run_id=run.ingestion_run_id,
            document_id=document.document_id,
            version_id=version.version_id,
        )

    async def _reject(
        self, tenant: TenantContext, record: UploadSessionRecord, *, code: str
    ) -> None:
        if record.staging_object_key:
            await self._objects.delete_object(tenant, object_key=record.staging_object_key)
        if record.final_object_key and record.status is not UploadSessionStatus.COMPLETED:
            await self._objects.delete_object(tenant, object_key=record.final_object_key)
        await self._release_id(record.document_reservation_id)
        await self._release_id(record.storage_reservation_id)
        record.status = UploadSessionStatus.REJECTED
        record.error_code = code
        record.document_id = None
        record.version_id = None
        await self._sessions.save(record)  # type: ignore[attr-defined]
        get_metrics().incr("upload_sessions_rejected_total")
        logger.info(
            "upload_session_rejected",
            tenant_id=str(tenant.tenant_id),
            upload_id=str(record.upload_id),
            error_code=code,
        )

    async def _expire_record(self, tenant: TenantContext, record: UploadSessionRecord) -> None:
        if record.status is not UploadSessionStatus.PENDING:
            return
        if record.staging_object_key:
            await self._objects.delete_object(tenant, object_key=record.staging_object_key)
        await self._release_id(record.document_reservation_id)
        await self._release_id(record.storage_reservation_id)
        record.status = UploadSessionStatus.EXPIRED
        record.error_code = "expired"
        await self._sessions.save(record)  # type: ignore[attr-defined]
        get_metrics().incr("upload_sessions_expired_total")
        logger.info(
            "upload_session_expired",
            tenant_id=str(record.tenant_id),
            upload_id=str(record.upload_id),
        )

    async def _authorize(self, tenant: TenantContext) -> None:
        if self._authorization is None:
            return
        from graph_rag.application.authorization.gate import require_action
        from graph_rag.application.authorization.service import PolicyAuthorizationService
        from graph_rag.domain.authorization.models import Action

        assert isinstance(self._authorization, PolicyAuthorizationService)
        require_action(self._authorization, tenant, Action.DOCUMENT_UPLOAD)

    async def _ensure_tenant(self, tenant: TenantContext) -> None:
        existing = await self._tenants.get_by_id(tenant.tenant_id)
        if existing is not None:
            return
        await self._tenants.upsert(
            TenantRecord(
                tenant_id=tenant.tenant_id,
                tenant_key=tenant.tenant_key or str(tenant.tenant_id),
                display_name=tenant.tenant_key,
            )
        )

    async def _quota(
        self, tenant: TenantContext, metric: QuotaMetric, quantity: int
    ) -> QuotaReservation | None:
        if self._quotas is None:
            return None
        result = self._quotas.reserve(  # type: ignore[attr-defined]
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            metric=metric,
            quantity=quantity,
        )
        if inspect.isawaitable(result):
            result = await result
        if result is None:
            return None
        if not isinstance(result, QuotaReservation):
            raise ValidationError("Quota reservation was not returned")
        return result

    async def _release(self, reservation: QuotaReservation | None) -> None:
        if reservation is None or self._quotas is None:
            return
        await self._release_id(reservation.reservation_id)

    async def _release_id(self, reservation_id: UUID | None) -> None:
        if reservation_id is None or self._quotas is None:
            return
        result = self._quotas.release(reservation_id=reservation_id)  # type: ignore[attr-defined]
        if inspect.isawaitable(result):
            await result

    async def _commit_quota(self, reservation_id: UUID | None, actual: int) -> None:
        if reservation_id is None or self._quotas is None:
            return
        result = self._quotas.commit(reservation_id=reservation_id, actual_quantity=actual)  # type: ignore[attr-defined]
        if inspect.isawaitable(result):
            await result
