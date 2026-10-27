"""Shared sqlite upload-session harness for integration checks."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from graph_rag.application.ingestion.upload_session import UploadSessionService
from graph_rag.application.quotas.service import InMemoryQuotaService
from graph_rag.domain.ids import new_id
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.outbox import InMemoryOutboxStore
from graph_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyIngestionRepository,
    SqlAlchemyTenantRepository,
)
from graph_rag.infrastructure.persistence.postgres.repositories.upload_sessions import (
    SqlAlchemyUploadSessionRepository,
)


def build_service(
    session: AsyncSession,
    store: object,
    quotas: InMemoryQuotaService,
    *,
    outbox: InMemoryOutboxStore | None = None,
    source_loader: object | None = None,
) -> tuple[UploadSessionService, InMemoryOutboxStore]:
    box = outbox or InMemoryOutboxStore()
    service = UploadSessionService(
        sessions=SqlAlchemyUploadSessionRepository(session),
        tenant_repo=SqlAlchemyTenantRepository(session),
        document_repo=SqlAlchemyDocumentRepository(session),
        ingestion_repo=SqlAlchemyIngestionRepository(session),
        object_store=store,
        quotas=quotas,
        outbox=box,
        source_loader=source_loader,
    )
    return service, box


def tenant_with_quota() -> tuple[TenantContext, InMemoryQuotaService]:
    quotas = InMemoryQuotaService()
    tenant_id = new_id()
    quotas.assign_default(tenant_id=tenant_id)
    return TenantContext(tenant_id=tenant_id, tenant_key="demo", user_id=new_id()), quotas
