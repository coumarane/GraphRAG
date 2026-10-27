"""Process-local upload sessions for unit tests and the memory backend."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from graph_rag.domain.ingestion.upload_session import UploadSessionRecord, UploadSessionStatus
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import NotFoundError


class InMemoryUploadSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, UploadSessionRecord] = {}

    async def add(self, record: UploadSessionRecord) -> UploadSessionRecord:
        self.sessions[record.upload_id] = record
        return record

    async def get(self, tenant: TenantContext, upload_id: UUID) -> UploadSessionRecord | None:
        record = self.sessions.get(upload_id)
        if record is None or record.tenant_id != tenant.tenant_id:
            return None
        return record

    async def save(self, record: UploadSessionRecord) -> UploadSessionRecord:
        if record.upload_id not in self.sessions:
            raise NotFoundError(
                "Upload session not found",
                details={"upload_id": str(record.upload_id)},
            )
        self.sessions[record.upload_id] = record
        return record

    async def list_pending_expired(self, now: datetime) -> list[UploadSessionRecord]:
        return [
            record
            for record in self.sessions.values()
            if record.status is UploadSessionStatus.PENDING and record.expires_at <= now
        ]
