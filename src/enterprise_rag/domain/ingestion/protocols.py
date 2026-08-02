"""Repository ports for PostgreSQL lifecycle persistence.

Every tenant-owned method requires ``TenantContext``.
"""

from __future__ import annotations

from typing import Protocol
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


class TenantRepository(Protocol):
    """Tenant registry port."""

    async def upsert(self, tenant: TenantRecord) -> TenantRecord:
        """Create or update a tenant."""
        ...

    async def get_by_id(self, tenant_id: UUID) -> TenantRecord | None:
        """Fetch tenant by id."""
        ...

    async def get_by_key(self, tenant_key: str) -> TenantRecord | None:
        """Fetch tenant by human-readable key."""
        ...


class DocumentRepository(Protocol):
    """Document and version port."""

    async def create_document(
        self,
        tenant: TenantContext,
        document: DocumentRecord,
    ) -> DocumentRecord:
        """Insert a document for the authorized tenant."""
        ...

    async def get_document(
        self,
        tenant: TenantContext,
        document_id: UUID,
    ) -> DocumentRecord | None:
        """Fetch a tenant-scoped document."""
        ...

    async def update_document(
        self,
        tenant: TenantContext,
        document: DocumentRecord,
    ) -> DocumentRecord:
        """Update a tenant-scoped document."""
        ...

    async def create_version(
        self,
        tenant: TenantContext,
        version: DocumentVersionRecord,
    ) -> DocumentVersionRecord:
        """Insert a document version."""
        ...

    async def get_version(
        self,
        tenant: TenantContext,
        version_id: UUID,
    ) -> DocumentVersionRecord | None:
        """Fetch a tenant-scoped document version."""
        ...

    async def get_version_by_content_hash(
        self,
        tenant: TenantContext,
        document_id: UUID,
        content_hash: str,
    ) -> DocumentVersionRecord | None:
        """Find a duplicate version by content hash."""
        ...


class IngestionRepository(Protocol):
    """Ingestion run and stage port."""

    async def create_run(
        self,
        tenant: TenantContext,
        run: IngestionRunRecord,
        stages: list[IngestionStageRecord],
    ) -> IngestionRunRecord:
        """Persist a new run with its stage rows."""
        ...

    async def get_run(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
    ) -> IngestionRunRecord | None:
        """Fetch a tenant-scoped ingestion run."""
        ...

    async def update_run(
        self,
        tenant: TenantContext,
        run: IngestionRunRecord,
    ) -> IngestionRunRecord:
        """Update run lifecycle fields."""
        ...

    async def list_stages(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
    ) -> list[IngestionStageRecord]:
        """List stages for a run ordered by pipeline position."""
        ...

    async def get_stage(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
        stage: IngestionStageName,
    ) -> IngestionStageRecord | None:
        """Fetch one stage row."""
        ...

    async def update_stage(
        self,
        tenant: TenantContext,
        stage: IngestionStageRecord,
    ) -> IngestionStageRecord:
        """Update a stage row."""
        ...

    async def add_parser_attempt(
        self,
        tenant: TenantContext,
        attempt: ParserAttemptRecord,
    ) -> ParserAttemptRecord:
        """Append a parser attempt audit row."""
        ...

    async def list_parser_attempts(
        self,
        tenant: TenantContext,
        ingestion_run_id: UUID,
    ) -> list[ParserAttemptRecord]:
        """List parser attempts for a run."""
        ...
