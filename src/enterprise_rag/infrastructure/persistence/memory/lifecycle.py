"""In-memory lifecycle repositories for API/CLI unit tests and local mode."""

from __future__ import annotations

from uuid import UUID

from enterprise_rag.domain.ingestion.records import (
    DocumentRecord,
    DocumentVersionRecord,
    IngestionRunRecord,
    IngestionStageRecord,
    ParserAttemptRecord,
    TenantRecord,
)
from enterprise_rag.domain.ingestion.stages import IngestionStageName
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import AuthorizationError, ConflictError, NotFoundError


class InMemoryTenantRepository:
    """Tenant registry used by local/dev containers."""

    def __init__(self) -> None:
        self.by_id: dict[UUID, TenantRecord] = {}
        self.by_key: dict[str, TenantRecord] = {}

    async def upsert(self, tenant: TenantRecord) -> TenantRecord:
        existing_key = self.by_key.get(tenant.tenant_key)
        if existing_key is not None and existing_key.tenant_id != tenant.tenant_id:
            raise ConflictError(
                "tenant_key already exists for a different tenant_id",
                details={"tenant_key": tenant.tenant_key},
            )
        self.by_id[tenant.tenant_id] = tenant
        self.by_key[tenant.tenant_key] = tenant
        return tenant

    async def get_by_id(self, tenant_id: UUID) -> TenantRecord | None:
        return self.by_id.get(tenant_id)

    async def get_by_key(self, tenant_key: str) -> TenantRecord | None:
        return self.by_key.get(tenant_key)


class InMemoryDocumentRepository:
    """Document/version store for local mode."""

    def __init__(self) -> None:
        self.documents: dict[tuple[UUID, UUID], DocumentRecord] = {}
        self.versions: dict[tuple[UUID, UUID], DocumentVersionRecord] = {}

    async def create_document(
        self,
        tenant: TenantContext,
        document: DocumentRecord,
    ) -> DocumentRecord:
        self._assert_tenant(tenant, document.tenant_id)
        key = (tenant.tenant_id, document.document_id)
        if key in self.documents:
            raise ConflictError("Document already exists")
        self.documents[key] = document
        return document

    async def get_document(
        self,
        tenant: TenantContext,
        document_id: UUID,
    ) -> DocumentRecord | None:
        return self.documents.get((tenant.tenant_id, document_id))

    async def list_documents(
        self,
        tenant: TenantContext,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[DocumentRecord], int]:
        items = [
            document
            for (owner, _document_id), document in self.documents.items()
            if owner == tenant.tenant_id
        ]
        items.sort(
            key=lambda doc: doc.updated_at or doc.created_at or doc.document_id.hex,
            reverse=True,
        )
        total = len(items)
        return items[offset : offset + limit], total

    async def update_document(
        self,
        tenant: TenantContext,
        document: DocumentRecord,
    ) -> DocumentRecord:
        self._assert_tenant(tenant, document.tenant_id)
        key = (tenant.tenant_id, document.document_id)
        if key not in self.documents:
            raise NotFoundError("Document not found")
        self.documents[key] = document
        return document

    async def create_version(
        self,
        tenant: TenantContext,
        version: DocumentVersionRecord,
    ) -> DocumentVersionRecord:
        self._assert_tenant(tenant, version.tenant_id)
        self.versions[(tenant.tenant_id, version.version_id)] = version
        return version

    async def get_version(
        self,
        tenant: TenantContext,
        version_id: UUID,
    ) -> DocumentVersionRecord | None:
        return self.versions.get((tenant.tenant_id, version_id))

    async def get_version_by_content_hash(
        self,
        tenant: TenantContext,
        document_id: UUID | None,
        content_hash: str,
    ) -> DocumentVersionRecord | None:
        for version in self.versions.values():
            if version.tenant_id != tenant.tenant_id:
                continue
            if version.content_hash != content_hash:
                continue
            if document_id is not None and version.document_id != document_id:
                continue
            return version
        return None

    async def lock_for_content_hash(
        self,
        tenant: TenantContext,
        content_hash: str,
    ) -> None:
        return None

    @staticmethod
    def _assert_tenant(tenant: TenantContext, owner: UUID) -> None:
        if tenant.tenant_id != owner:
            raise AuthorizationError("Document tenant mismatch")


class InMemoryIngestionRepository:
    """Ingestion run/stage store for local mode."""

    def __init__(self) -> None:
        self.runs: dict[tuple[UUID, UUID], IngestionRunRecord] = {}
        self.stages: dict[tuple[UUID, UUID], list[IngestionStageRecord]] = {}
        self.attempts: dict[tuple[UUID, UUID], list[ParserAttemptRecord]] = {}

    async def create_run(
        self,
        tenant: TenantContext,
        run: IngestionRunRecord,
        stages: list[IngestionStageRecord],
    ) -> IngestionRunRecord:
        if run.tenant_id != tenant.tenant_id:
            raise AuthorizationError("Run tenant mismatch")
        key = (tenant.tenant_id, run.ingestion_run_id)
        self.runs[key] = run
        self.stages[key] = list(stages)
        self.attempts[key] = []
        return run

    async def get_run(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
    ) -> IngestionRunRecord | None:
        return self.runs.get((tenant.tenant_id, ingestion_run_id))

    async def update_run(
        self,
        tenant: TenantContext,
        run: IngestionRunRecord,
    ) -> IngestionRunRecord:
        key = (tenant.tenant_id, run.ingestion_run_id)
        if key not in self.runs:
            raise NotFoundError("Ingestion run not found")
        self.runs[key] = run
        return run

    async def list_stages(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
    ) -> list[IngestionStageRecord]:
        return list(self.stages.get((tenant.tenant_id, ingestion_run_id), []))

    async def get_stage(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
        stage: IngestionStageName,
    ) -> IngestionStageRecord | None:
        for item in await self.list_stages(tenant, ingestion_run_id):
            if item.stage is stage:
                return item
        return None

    async def update_stage(
        self,
        tenant: TenantContext,
        stage: IngestionStageRecord,
    ) -> IngestionStageRecord:
        key = (tenant.tenant_id, stage.ingestion_run_id)
        rows = self.stages.get(key)
        if rows is None:
            raise NotFoundError("Ingestion run stages not found")
        for index, item in enumerate(rows):
            if item.stage is stage.stage:
                rows[index] = stage
                return stage
        rows.append(stage)
        return stage

    async def add_parser_attempt(
        self,
        tenant: TenantContext,
        attempt: ParserAttemptRecord,
    ) -> ParserAttemptRecord:
        key = (tenant.tenant_id, attempt.ingestion_run_id)
        self.attempts.setdefault(key, []).append(attempt)
        return attempt

    async def list_parser_attempts(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
    ) -> list[ParserAttemptRecord]:
        return list(self.attempts.get((tenant.tenant_id, ingestion_run_id), []))
