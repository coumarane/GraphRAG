"""``delete_document`` must actually remove the row, not just flip a status.

Regression coverage for an incident where a soft-deleted document (status
flipped to DELETED, row left in place) got resurrected back to FAILED by
a zombie ingestion run that outlived the deletion. A row that no longer
exists can't be resurrected. This exercises the real Postgres schema (via
an in-memory SQLite engine sharing the same Alembic-defined FK/cascade
shape) to prove the DB-level ``ON DELETE CASCADE`` chain actually holds,
not just that the in-memory test double happens to remove a dict entry.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.ingestion.records import (
    DocumentRecord,
    DocumentVersionRecord,
    IngestionRunRecord,
    IngestionStageRecord,
)
from graph_rag.domain.ingestion.stages import (
    DocumentLifecycleStatus,
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
)
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.postgres.base import Base
from graph_rag.infrastructure.persistence.postgres.models import (
    DocumentModel,
    DocumentVersionModel,
    IngestionRunModel,
    IngestionStageModel,
)
from graph_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyIngestionRepository,
)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(_sqlite_fk_pragma())
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        await db_session.execute(_sqlite_fk_pragma())
        yield db_session
    await engine.dispose()


def _sqlite_fk_pragma():
    from sqlalchemy import text

    return text("PRAGMA foreign_keys = ON")


@pytest.mark.asyncio
async def test_delete_document_cascades_versions_and_ingestion_rows(
    session: AsyncSession,
) -> None:
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    document_repo = SqlAlchemyDocumentRepository(session)
    ingestion_repo = SqlAlchemyIngestionRepository(session)

    document_id = new_id()
    version_id = new_id()
    run_id = new_id()

    await document_repo.create_document(
        tenant,
        DocumentRecord(
            document_id=document_id,
            tenant_id=tenant.tenant_id,
            title="to-delete",
            status=DocumentLifecycleStatus.READY,
            current_version_id=version_id,
        ),
    )
    await document_repo.create_version(
        tenant,
        DocumentVersionRecord(
            version_id=version_id,
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_number=1,
            source_filename="r.pdf",
            mime_type="application/pdf",
            content_hash=content_sha256_hex("r"),
            status=DocumentLifecycleStatus.READY,
        ),
    )
    await ingestion_repo.create_run(
        tenant,
        IngestionRunRecord(
            ingestion_run_id=run_id,
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            status=IngestionRunStatus.FAILED,
            content_hash=content_sha256_hex("r"),
            config_fingerprint="fp-v1",
        ),
        [
            IngestionStageRecord(
                stage_id=new_id(),
                tenant_id=tenant.tenant_id,
                ingestion_run_id=run_id,
                stage=IngestionStageName.PARSE,
                status=StageStatus.FAILED,
            )
        ],
    )
    await session.commit()

    deleted = await document_repo.delete_document(tenant, document_id)
    await session.commit()
    assert deleted is True

    assert await document_repo.get_document(tenant, document_id) is None
    assert await document_repo.get_version(tenant, version_id) is None
    assert await ingestion_repo.get_run(tenant, run_id) is None

    # Confirm at the raw-row level too, not just through the repo's own
    # tenant-scoped queries.
    assert (
        await session.execute(select(DocumentModel).where(DocumentModel.document_id == document_id))
    ).scalar_one_or_none() is None
    assert (
        await session.execute(
            select(DocumentVersionModel).where(DocumentVersionModel.version_id == version_id)
        )
    ).scalar_one_or_none() is None
    assert (
        await session.execute(
            select(IngestionRunModel).where(IngestionRunModel.ingestion_run_id == run_id)
        )
    ).scalar_one_or_none() is None
    assert (
        await session.execute(
            select(IngestionStageModel).where(IngestionStageModel.ingestion_run_id == run_id)
        )
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_document_returns_false_for_unknown_document(
    session: AsyncSession,
) -> None:
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    document_repo = SqlAlchemyDocumentRepository(session)
    assert await document_repo.delete_document(tenant, new_id()) is False
