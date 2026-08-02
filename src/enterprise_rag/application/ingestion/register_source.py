"""Register a local file or remote URL as a document version and store the original."""

from __future__ import annotations

from dataclasses import dataclass
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
from enterprise_rag.domain.storage.object_keys import original_object_key
from enterprise_rag.domain.storage.protocols import ObjectStore, SourceBytes, SourceLoader
from enterprise_rag.domain.tenant import TenantContext


class RegisterSourceRequest(BaseModel):
    """Input for source registration."""

    model_config = ConfigDict(extra="forbid")

    local_path: str | None = None
    source_url: str | None = None
    document_id: UUID | None = None
    title: str | None = None
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

    async def execute(
        self,
        tenant: TenantContext,
        request: RegisterSourceRequest,
    ) -> RegisterSourceResult:
        tenant.ensure_authorized()
        source = await self._load_source(request)
        content_hash = self._hash(source.content)

        await self._ensure_tenant(tenant)

        document_id = request.document_id or new_id()
        existing_document = await self.document_repo.get_document(tenant, document_id)
        if existing_document is None:
            existing_document = await self.document_repo.create_document(
                tenant,
                DocumentRecord(
                    document_id=document_id,
                    tenant_id=tenant.tenant_id,
                    title=request.title or source.filename,
                    document_type=request.document_type,
                    status=DocumentLifecycleStatus.INGESTING,
                    tags=list(request.tags),
                    security_labels=list(request.security_labels),
                ),
            )

        if not request.force_new_version:
            duplicate = await self.document_repo.get_version_by_content_hash(
                tenant,
                document_id,
                content_hash,
            )
            if duplicate is not None and duplicate.original_object_key:
                run = await self._create_run(
                    tenant=tenant,
                    document_id=document_id,
                    version_id=duplicate.version_id,
                    content_hash=content_hash,
                    parser_requested=request.parser_requested,
                    correlation_id=request.correlation_id,
                )
                return RegisterSourceResult(
                    tenant_id=tenant.tenant_id,
                    document_id=document_id,
                    version_id=duplicate.version_id,
                    ingestion_run_id=run.ingestion_run_id,
                    content_hash=content_hash,
                    mime_type=source.mime_type,
                    source_filename=source.filename,
                    byte_size=len(source.content),
                    original_object_key=duplicate.original_object_key,
                    duplicate_version=True,
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
            title=request.title or existing_document.title,
            document_type=request.document_type or existing_document.document_type,
            status=DocumentLifecycleStatus.INGESTING,
            current_version_id=version.version_id,
            tags=list(request.tags) if request.tags else existing_document.tags,
            security_labels=(
                list(request.security_labels)
                if request.security_labels
                else existing_document.security_labels
            ),
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
