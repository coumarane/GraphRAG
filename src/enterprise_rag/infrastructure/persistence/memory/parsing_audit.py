"""In-memory parsing audit repository for tests and local runtime."""

from __future__ import annotations

from uuid import UUID

from enterprise_rag.domain.parsing.audit import ParsingAuditSnapshot
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import ConflictError


class InMemoryParsingAuditRepository:
    """Process-local insert-only audit store."""

    def __init__(self) -> None:
        self._by_run: dict[tuple[UUID, UUID, UUID], ParsingAuditSnapshot] = {}

    async def save_snapshot(
        self,
        tenant: TenantContext,
        snapshot: ParsingAuditSnapshot,
    ) -> ParsingAuditSnapshot:
        tenant.ensure_authorized()
        key = (
            tenant.tenant_id,
            snapshot.document.document_id,
            snapshot.document.ingestion_run_id,
        )
        if key in self._by_run:
            raise ConflictError(
                "Parse report already exists for ingestion run",
                details={"ingestion_run_id": str(snapshot.document.ingestion_run_id)},
            )
        # Deep-ish copy via model_copy to keep immutability after save.
        stored = snapshot.model_copy(deep=True)
        self._by_run[key] = stored
        return stored

    async def get_snapshot(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        ingestion_run_id: UUID,
    ) -> ParsingAuditSnapshot | None:
        tenant.ensure_authorized()
        return self._by_run.get((tenant.tenant_id, document_id, ingestion_run_id))

    async def list_run_ids(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
    ) -> list[UUID]:
        tenant.ensure_authorized()
        runs = [
            run_id
            for (tenant_id, doc_id, run_id) in self._by_run
            if tenant_id == tenant.tenant_id and doc_id == document_id
        ]
        return sorted(runs, key=str)
