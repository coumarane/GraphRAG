"""PostgreSQL repository unit tests using in-memory SQLite."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from graph_rag.domain.ids import content_sha256_hex, new_id
from graph_rag.domain.ingestion import (
    DocumentLifecycleStatus,
    DocumentRecord,
    DocumentVersionRecord,
    IngestionRunRecord,
    IngestionRunStatus,
    IngestionStageName,
    StageStatus,
    build_persisted_stage_records,
)
from graph_rag.domain.ingestion.records import TenantRecord
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.postgres.base import Base
from graph_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentRepository,
    SqlAlchemyIngestionRepository,
    SqlAlchemyTenantRepository,
)
from graph_rag.shared.exceptions import TenantError


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_document_repository_enforces_tenant_scope(session: AsyncSession) -> None:
    tenants = SqlAlchemyTenantRepository(session)
    documents = SqlAlchemyDocumentRepository(session)

    tenant_a = TenantRecord(tenant_id=new_id(), tenant_key="alpha")
    tenant_b = TenantRecord(tenant_id=new_id(), tenant_key="bravo")
    await tenants.upsert(tenant_a)
    await tenants.upsert(tenant_b)

    ctx_a = TenantContext(tenant_id=tenant_a.tenant_id, tenant_key="alpha")
    ctx_b = TenantContext(tenant_id=tenant_b.tenant_id, tenant_key="bravo")

    document = DocumentRecord(
        document_id=new_id(),
        tenant_id=tenant_a.tenant_id,
        title="Spec",
        status=DocumentLifecycleStatus.REGISTERED,
    )
    await documents.create_document(ctx_a, document)

    assert await documents.get_document(ctx_a, document.document_id) is not None
    assert await documents.get_document(ctx_b, document.document_id) is None

    with pytest.raises(TenantError):
        await documents.create_document(
            ctx_b,
            DocumentRecord(
                document_id=new_id(),
                tenant_id=tenant_a.tenant_id,
                title="leak",
            ),
        )


@pytest.mark.asyncio
async def test_ingestion_run_and_stages_roundtrip(session: AsyncSession) -> None:
    tenants = SqlAlchemyTenantRepository(session)
    documents = SqlAlchemyDocumentRepository(session)
    ingestions = SqlAlchemyIngestionRepository(session)

    tenant = TenantRecord(tenant_id=new_id(), tenant_key="demo")
    await tenants.upsert(tenant)
    ctx = TenantContext(tenant_id=tenant.tenant_id, tenant_key="demo")

    document_id = new_id()
    version_id = new_id()
    await documents.create_document(
        ctx,
        DocumentRecord(document_id=document_id, tenant_id=tenant.tenant_id, title="Doc"),
    )
    await documents.create_version(
        ctx,
        DocumentVersionRecord(
            version_id=version_id,
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_number=1,
            source_filename="doc.pdf",
            mime_type="application/pdf",
            content_hash=content_sha256_hex("bytes"),
        ),
    )

    run_id = new_id()
    stages = build_persisted_stage_records(tenant_id=tenant.tenant_id, ingestion_run_id=run_id)
    run = IngestionRunRecord(
        ingestion_run_id=run_id,
        tenant_id=tenant.tenant_id,
        document_id=document_id,
        version_id=version_id,
        status=IngestionRunStatus.PENDING,
        parser_requested="auto",
    )
    await ingestions.create_run(ctx, run, stages)

    loaded = await ingestions.get_run(ctx, run_id)
    assert loaded is not None
    listed = await ingestions.list_stages(ctx, run_id)
    assert len(listed) == 22
    assert listed[0].stage is IngestionStageName.VALIDATE

    stage = listed[0]
    stage.status = StageStatus.RUNNING
    stage.attempt_count = 1
    updated = await ingestions.update_stage(ctx, stage)
    assert updated.status is StageStatus.RUNNING
    assert updated.attempt_count == 1
