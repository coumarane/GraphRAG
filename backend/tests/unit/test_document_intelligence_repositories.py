"""Document Intelligence custom-model repository tests (Phase 2)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from graph_rag.domain.document_intelligence.records import (
    DocumentExtractedFieldRecord,
    DocumentExtractionRunRecord,
    DocumentIntelligenceModelFieldRecord,
    DocumentIntelligenceModelRecord,
)
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.records import TenantRecord
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.persistence.memory.document_intelligence import (
    InMemoryDocumentExtractionRepository,
    InMemoryDocumentIntelligenceModelRepository,
)
from graph_rag.infrastructure.persistence.postgres.base import Base
from graph_rag.infrastructure.persistence.postgres.repositories import (
    SqlAlchemyDocumentExtractionRepository,
    SqlAlchemyDocumentIntelligenceModelRepository,
    SqlAlchemyTenantRepository,
)
from graph_rag.shared.exceptions import AuthorizationError, ConflictError


def _model_record(
    tenant_id, *, model_key: str = "custom-widget"
) -> DocumentIntelligenceModelRecord:
    model_id = new_id()
    return DocumentIntelligenceModelRecord(
        model_id=model_id,
        tenant_id=tenant_id,
        model_key=model_key,
        name="Custom Widget",
        model_type="custom",
        is_builtin=False,
        fields=[
            DocumentIntelligenceModelFieldRecord(
                field_id=new_id(),
                model_id=model_id,
                tenant_id=tenant_id,
                name="serial_number",
                label="Serial number",
                field_type="string",
                default_selected=True,
                sort_order=0,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_in_memory_repo_create_then_list_round_trip() -> None:
    repo = InMemoryDocumentIntelligenceModelRepository()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    record = _model_record(tenant.tenant_id)

    created = await repo.create_model(tenant, record)
    assert created.model_key == "custom-widget"
    assert len(created.fields) == 1

    listed = await repo.list_models(tenant)
    assert [item.model_id for item in listed] == [record.model_id]


@pytest.mark.asyncio
async def test_in_memory_repo_rejects_duplicate_model_id() -> None:
    repo = InMemoryDocumentIntelligenceModelRepository()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    record = _model_record(tenant.tenant_id)
    await repo.create_model(tenant, record)
    with pytest.raises(ConflictError):
        await repo.create_model(tenant, record)


@pytest.mark.asyncio
async def test_in_memory_repo_rejects_tenant_mismatch() -> None:
    repo = InMemoryDocumentIntelligenceModelRepository()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    other_tenant_id = new_id()
    record = _model_record(other_tenant_id)
    with pytest.raises(AuthorizationError):
        await repo.create_model(tenant, record)


@pytest.mark.asyncio
async def test_in_memory_repo_list_is_tenant_scoped() -> None:
    repo = InMemoryDocumentIntelligenceModelRepository()
    tenant_a = TenantContext(tenant_id=new_id(), tenant_key="alpha")
    tenant_b = TenantContext(tenant_id=new_id(), tenant_key="bravo")
    await repo.create_model(tenant_a, _model_record(tenant_a.tenant_id))
    await repo.create_model(tenant_b, _model_record(tenant_b.tenant_id, model_key="other"))

    listed_a = await repo.list_models(tenant_a)
    assert len(listed_a) == 1
    assert listed_a[0].model_key == "custom-widget"


def _run_record(
    tenant_id, *, document_id=None, version_id=None, model_key: str = "sds"
) -> DocumentExtractionRunRecord:
    return DocumentExtractionRunRecord(
        run_id=new_id(),
        tenant_id=tenant_id,
        document_id=document_id or new_id(),
        version_id=version_id or new_id(),
        model_key=model_key,
        provider="internal",
        plugin_version="0.4.0",
        status="completed",
        selected_fields=["product_name"],
    )


def _field_record(tenant_id, run_id) -> DocumentExtractedFieldRecord:
    return DocumentExtractedFieldRecord(
        extracted_field_id=new_id(),
        tenant_id=tenant_id,
        run_id=run_id,
        name="product_name",
        value="Acme Widget",
        confidence=0.8,
        confidence_band="MEDIUM",
        extraction_method="RULES",
    )


@pytest.mark.asyncio
async def test_in_memory_extraction_repo_create_run_then_add_fields() -> None:
    repo = InMemoryDocumentExtractionRepository()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    run = _run_record(tenant.tenant_id)

    created = await repo.create_run(tenant, run)
    assert created.status == "completed"

    fields = await repo.add_extracted_fields(
        tenant, created.run_id, [_field_record(tenant.tenant_id, created.run_id)]
    )
    assert len(fields) == 1

    fetched = await repo.get_run(tenant, created.run_id)
    assert fetched is not None
    listed_fields = await repo.list_fields_for_run(tenant, created.run_id)
    assert [f.name for f in listed_fields] == ["product_name"]


@pytest.mark.asyncio
async def test_in_memory_extraction_repo_rejects_tenant_mismatch() -> None:
    repo = InMemoryDocumentExtractionRepository()
    tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
    run = _run_record(new_id())
    with pytest.raises(AuthorizationError):
        await repo.create_run(tenant, run)


@pytest.mark.asyncio
async def test_in_memory_extraction_repo_list_runs_for_version_is_tenant_scoped() -> None:
    repo = InMemoryDocumentExtractionRepository()
    tenant_a = TenantContext(tenant_id=new_id(), tenant_key="alpha")
    tenant_b = TenantContext(tenant_id=new_id(), tenant_key="bravo")
    document_id = new_id()
    version_id = new_id()
    await repo.create_run(
        tenant_a, _run_record(tenant_a.tenant_id, document_id=document_id, version_id=version_id)
    )
    await repo.create_run(
        tenant_b, _run_record(tenant_b.tenant_id, document_id=document_id, version_id=version_id)
    )

    listed_a = await repo.list_runs_for_version(tenant_a, document_id, version_id)
    assert len(listed_a) == 1


@pytest.fixture
async def sqlite_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_sqlalchemy_repo_create_then_list_round_trip(sqlite_session: AsyncSession) -> None:
    tenants = SqlAlchemyTenantRepository(sqlite_session)
    repo = SqlAlchemyDocumentIntelligenceModelRepository(sqlite_session)

    tenant_record = TenantRecord(tenant_id=new_id(), tenant_key="demo")
    await tenants.upsert(tenant_record)
    tenant = TenantContext(tenant_id=tenant_record.tenant_id, tenant_key="demo")

    record = _model_record(tenant.tenant_id)
    created = await repo.create_model(tenant, record)
    assert created.model_key == "custom-widget"
    assert len(created.fields) == 1
    assert created.fields[0].name == "serial_number"

    listed = await repo.list_models(tenant)
    assert [item.model_id for item in listed] == [record.model_id]
    assert len(listed[0].fields) == 1

    fetched = await repo.get_model(tenant, record.model_id)
    assert fetched is not None
    assert fetched.name == "Custom Widget"


@pytest.mark.asyncio
async def test_sqlalchemy_repo_list_is_tenant_scoped(sqlite_session: AsyncSession) -> None:
    tenants = SqlAlchemyTenantRepository(sqlite_session)
    repo = SqlAlchemyDocumentIntelligenceModelRepository(sqlite_session)

    tenant_a_record = TenantRecord(tenant_id=new_id(), tenant_key="alpha")
    tenant_b_record = TenantRecord(tenant_id=new_id(), tenant_key="bravo")
    await tenants.upsert(tenant_a_record)
    await tenants.upsert(tenant_b_record)
    tenant_a = TenantContext(tenant_id=tenant_a_record.tenant_id, tenant_key="alpha")
    tenant_b = TenantContext(tenant_id=tenant_b_record.tenant_id, tenant_key="bravo")

    await repo.create_model(tenant_a, _model_record(tenant_a.tenant_id))
    await repo.create_model(tenant_b, _model_record(tenant_b.tenant_id, model_key="other"))

    listed_a = await repo.list_models(tenant_a)
    assert len(listed_a) == 1
    assert listed_a[0].model_key == "custom-widget"


@pytest.mark.asyncio
async def test_sqlalchemy_extraction_repo_create_run_then_add_fields(
    sqlite_session: AsyncSession,
) -> None:
    tenants = SqlAlchemyTenantRepository(sqlite_session)
    repo = SqlAlchemyDocumentExtractionRepository(sqlite_session)

    tenant_record = TenantRecord(tenant_id=new_id(), tenant_key="demo")
    await tenants.upsert(tenant_record)
    tenant = TenantContext(tenant_id=tenant_record.tenant_id, tenant_key="demo")

    run = _run_record(tenant.tenant_id)
    created = await repo.create_run(tenant, run)
    assert created.model_key == "sds"
    assert created.status == "completed"

    fields = await repo.add_extracted_fields(
        tenant, created.run_id, [_field_record(tenant.tenant_id, created.run_id)]
    )
    assert len(fields) == 1
    assert fields[0].value == "Acme Widget"

    fetched = await repo.get_run(tenant, created.run_id)
    assert fetched is not None
    assert fetched.run_id == created.run_id

    listed_fields = await repo.list_fields_for_run(tenant, created.run_id)
    assert [f.name for f in listed_fields] == ["product_name"]


@pytest.mark.asyncio
async def test_sqlalchemy_extraction_repo_list_runs_for_version_is_tenant_scoped(
    sqlite_session: AsyncSession,
) -> None:
    tenants = SqlAlchemyTenantRepository(sqlite_session)
    repo = SqlAlchemyDocumentExtractionRepository(sqlite_session)

    tenant_a_record = TenantRecord(tenant_id=new_id(), tenant_key="alpha")
    tenant_b_record = TenantRecord(tenant_id=new_id(), tenant_key="bravo")
    await tenants.upsert(tenant_a_record)
    await tenants.upsert(tenant_b_record)
    tenant_a = TenantContext(tenant_id=tenant_a_record.tenant_id, tenant_key="alpha")
    tenant_b = TenantContext(tenant_id=tenant_b_record.tenant_id, tenant_key="bravo")

    document_id = new_id()
    version_id = new_id()
    await repo.create_run(
        tenant_a, _run_record(tenant_a.tenant_id, document_id=document_id, version_id=version_id)
    )
    await repo.create_run(
        tenant_b, _run_record(tenant_b.tenant_id, document_id=document_id, version_id=version_id)
    )

    listed_a = await repo.list_runs_for_version(tenant_a, document_id, version_id)
    assert len(listed_a) == 1
