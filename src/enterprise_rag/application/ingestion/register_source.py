"""Register a local file or remote URL as a document version and store the original."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.ingestion.protocols import (
    DocumentRepository,
    IngestionRepository,
    TenantRepository,
)
from enterprise_rag.domain.ingestion.records import (
    DocumentRecord,
    DocumentVersionRecord,
    IngestionRunRecord,
    TenantRecord,
)
from enterprise_rag.domain.ingestion.stages import (
    DocumentLifecycleStatus,
    IngestionRunStatus,
)
from enterprise_rag.domain.ingestion.state_machine import build_persisted_stage_records
from enterprise_rag.domain.storage.object_keys import original_object_key, sanitize_filename
from enterprise_rag.domain.storage.protocols import ObjectStore, SourceBytes, SourceLoader
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import ConflictError


def _title_from_source(
    *,
    source_filename: str | None,
    request_title: str | None,
    loaded_filename: str,
) -> str:
    """Name documents from the original upload filename when available.

    Multipart uploads pass ``source_filename``. Prefer that stem so a stale
    form title cannot mislabel a different file.
    """
    file_stem = PurePosixPath(loaded_filename).stem if loaded_filename else None
    if source_filename:
        stem = PurePosixPath(sanitize_filename(source_filename)).stem
        return stem.replace("_", " ")
    explicit = (request_title or "").strip()
    return explicit or (file_stem.replace("_", " ") if file_stem else None) or loaded_filename or "Untitled"


class RegisterSourceRequest(BaseModel):
    """Input for source registration."""

    model_config = ConfigDict(extra="forbid")

    local_path: str | None = None
    source_url: str | None = None
    document_id: UUID | None = None
    title: str | None = None
    source_filename: str | None = None
    document_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    security_labels: list[str] = Field(default_factory=list)
    parser_requested: str | None = "auto"
    correlation_id: str | None = None
    force_new_version: bool = False


class RegisterSourceResult(BaseModel):
    """Outcome of VALIDATE/HASH/REGISTER_DOCUMENT/STORE_ORIGINAL."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    ingestion_run_id: UUID
    content_hash: str
    mime_type: str
    source_filename: str
    byte_size: int
    original_object_key: str
    duplicate_version: bool = False


@dataclass
class RegisterSourceService:
    """Application use case for source intake and original blob persistence."""

    tenant_repo: TenantRepository
    document_repo: DocumentRepository
    ingestion_repo: IngestionRepository
    object_store: ObjectStore
    source_loader: SourceLoader
    config_fingerprint: str = "intake-v1"
    authorization: object | None = None
    quotas: object | None = None

    async def execute(
        self,
        tenant: TenantContext,
        request: RegisterSourceRequest,
    ) -> RegisterSourceResult:
        tenant.ensure_authorized()
        if self.authorization is not None:
            from enterprise_rag.application.authorization.gate import require_action
            from enterprise_rag.application.authorization.service import (
                PolicyAuthorizationService,
            )
            from enterprise_rag.domain.authorization.models import Action

            assert isinstance(self.authorization, PolicyAuthorizationService)
            require_action(self.authorization, tenant, Action.DOCUMENT_UPLOAD)

        doc_reservation = None
        storage_reservation = None
        if self.quotas is not None:
            from enterprise_rag.application.authorization.gate import reserve_quota
            from enterprise_rag.application.quotas.service import InMemoryQuotaService
            from enterprise_rag.domain.quotas.models import QuotaMetric

            assert isinstance(self.quotas, InMemoryQuotaService)
            doc_reservation = reserve_quota(
                self.quotas, tenant, metric=QuotaMetric.DOCUMENTS, quantity=1
            )

        try:
            return await self._execute_inner(
                tenant,
                request,
                storage_reservation_holder={"res": storage_reservation},
                doc_reservation=doc_reservation,
            )
        except Exception:
            if self.quotas is not None:
                if doc_reservation is not None:
                    self.quotas.release(reservation_id=doc_reservation.reservation_id)
                # storage reservation released inside when raised after reserve
            raise

    async def _execute_inner(
        self,
        tenant: TenantContext,
        request: RegisterSourceRequest,
        *,
        storage_reservation_holder: dict[str, object],
        doc_reservation: object | None,
    ) -> RegisterSourceResult:
        source = await self._load_source(request)
        if request.source_filename:
            source = source.model_copy(
                update={"filename": sanitize_filename(request.source_filename)}
            )
        content_hash = self._hash(source.content)

        storage_reservation = None
        try:
            if self.quotas is not None:
                from enterprise_rag.application.authorization.gate import reserve_quota
                from enterprise_rag.application.quotas.service import InMemoryQuotaService
                from enterprise_rag.domain.quotas.models import QuotaMetric

                assert isinstance(self.quotas, InMemoryQuotaService)
                storage_reservation = reserve_quota(
                    self.quotas,
                    tenant,
                    metric=QuotaMetric.STORAGE_BYTES,
                    quantity=max(1, len(source.content)),
                )
                storage_reservation_holder["res"] = storage_reservation

            await self._ensure_tenant(tenant)
            # Serialize concurrent uploads of the same bytes until this transaction commits.
            await self.document_repo.lock_for_content_hash(tenant, content_hash)

            if not request.force_new_version:
                # Tenant-wide guard: identical bytes must not create another document.
                duplicate = await self.document_repo.get_version_by_content_hash(
                    tenant,
                    None,
                    content_hash,
                )
                if duplicate is not None and duplicate.original_object_key:
                    raise ConflictError(
                        "This document is already uploaded. Identical content was found.",
                        details={
                            "document_id": str(duplicate.document_id),
                            "version_id": str(duplicate.version_id),
                            "content_hash": content_hash,
                            "source_filename": duplicate.source_filename,
                            "title": request.title,
                        },
                    )

            document_id = request.document_id or new_id()
            display_title = _title_from_source(
                source_filename=request.source_filename,
                request_title=request.title,
                loaded_filename=source.filename,
            )
            existing_document = await self.document_repo.get_document(tenant, document_id)
            if existing_document is None:
                existing_document = await self.document_repo.create_document(
                    tenant,
                    DocumentRecord(
                        document_id=document_id,
                        tenant_id=tenant.tenant_id,
                        title=display_title,
                        document_type=request.document_type,
                        status=DocumentLifecycleStatus.INGESTING,
                        tags=list(request.tags),
                        security_labels=list(request.security_labels),
                        owner_user_id=tenant.user_id,
                    ),
                )

            version_number = await self._next_version_number(tenant, document_id)
            version_id = new_id()
            object_key = original_object_key(
                tenant_id=tenant.tenant_id,
                document_id=document_id,
                version_id=version_id,
                filename=source.filename,
            )

            await self.object_store.ensure_bucket()
            stored = await self.object_store.put_bytes(
                tenant,
                object_key=object_key,
                data=source.content,
                content_type=source.mime_type,
                content_hash=content_hash,
            )

            version = await self.document_repo.create_version(
                tenant,
                DocumentVersionRecord(
                    version_id=version_id,
                    tenant_id=tenant.tenant_id,
                    document_id=document_id,
                    version_number=version_number,
                    source_filename=source.filename,
                    mime_type=source.mime_type,
                    content_hash=content_hash,
                    byte_size=stored.byte_size,
                    original_object_key=stored.object_key,
                    status=DocumentLifecycleStatus.INGESTING,
                    metadata={
                        "source_uri": source.source_uri,
                    },
                ),
            )

            updated_document = DocumentRecord(
                document_id=existing_document.document_id,
                tenant_id=existing_document.tenant_id,
                title=display_title or existing_document.title,
                document_type=request.document_type or existing_document.document_type,
                status=DocumentLifecycleStatus.INGESTING,
                current_version_id=version.version_id,
                tags=list(request.tags) if request.tags else existing_document.tags,
                security_labels=(
                    list(request.security_labels)
                    if request.security_labels
                    else existing_document.security_labels
                ),
                owner_user_id=existing_document.owner_user_id or tenant.user_id,
                department=existing_document.department,
                country=existing_document.country,
                business_unit=existing_document.business_unit,
                classification=existing_document.classification,
                required_clearance=existing_document.required_clearance,
                allowed_groups=list(existing_document.allowed_groups),
                metadata=existing_document.metadata,
            )
            await self.document_repo.update_document(tenant, updated_document)

            run = await self._create_run(
                tenant=tenant,
                document_id=document_id,
                version_id=version_id,
                content_hash=content_hash,
                parser_requested=request.parser_requested,
                correlation_id=request.correlation_id,
            )

            if self.quotas is not None and doc_reservation is not None:
                self.quotas.commit(
                    reservation_id=doc_reservation.reservation_id,  # type: ignore[attr-defined]
                    actual_quantity=1,
                )
            if self.quotas is not None and storage_reservation is not None:
                self.quotas.commit(
                    reservation_id=storage_reservation.reservation_id,
                    actual_quantity=stored.byte_size,
                )

            return RegisterSourceResult(
                tenant_id=tenant.tenant_id,
                document_id=document_id,
                version_id=version_id,
                ingestion_run_id=run.ingestion_run_id,
                content_hash=content_hash,
                mime_type=source.mime_type,
                source_filename=source.filename,
                byte_size=stored.byte_size,
                original_object_key=stored.object_key,
                duplicate_version=False,
            )
        except Exception:
            if self.quotas is not None and storage_reservation is not None:
                self.quotas.release(reservation_id=storage_reservation.reservation_id)
            raise

    async def _load_source(self, request: RegisterSourceRequest) -> SourceBytes:
        if bool(request.local_path) == bool(request.source_url):
            from enterprise_rag.shared.exceptions import ValidationError

            raise ValidationError("Provide exactly one of local_path or source_url")
        if request.local_path:
            return await self.source_loader.load_local(request.local_path)
        assert request.source_url is not None
        return await self.source_loader.load_url(request.source_url)

    def _hash(self, data: bytes) -> str:
        from enterprise_rag.domain.ids import content_sha256_hex

        return content_sha256_hex(data)

    async def _ensure_tenant(self, tenant: TenantContext) -> None:
        existing = await self.tenant_repo.get_by_id(tenant.tenant_id)
        if existing is not None:
            return
        await self.tenant_repo.upsert(
            TenantRecord(
                tenant_id=tenant.tenant_id,
                tenant_key=tenant.tenant_key or str(tenant.tenant_id),
                display_name=tenant.tenant_key,
            )
        )

    async def _next_version_number(self, tenant: TenantContext, document_id: UUID) -> int:
        # Simple increment: look up current version if present.
        document = await self.document_repo.get_document(tenant, document_id)
        if document is None or document.current_version_id is None:
            return 1
        current = await self.document_repo.get_version(tenant, document.current_version_id)
        if current is None:
            return 1
        return current.version_number + 1

    async def _create_run(
        self,
        *,
        tenant: TenantContext,
        document_id: UUID,
        version_id: UUID,
        content_hash: str,
        parser_requested: str | None,
        correlation_id: str | None,
    ) -> IngestionRunRecord:
        run_id = new_id()
        stages = build_persisted_stage_records(
            tenant_id=tenant.tenant_id,
            ingestion_run_id=run_id,
        )
        return await self.ingestion_repo.create_run(
            tenant,
            IngestionRunRecord(
                ingestion_run_id=run_id,
                tenant_id=tenant.tenant_id,
                document_id=document_id,
                version_id=version_id,
                status=IngestionRunStatus.PENDING,
                parser_requested=parser_requested,
                config_fingerprint=self.config_fingerprint,
                content_hash=content_hash,
                correlation_id=correlation_id,
            ),
            stages,
        )
