"""Two database sessions share one quota budget."""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from graph_rag.application.quotas.postgres import PostgresQuotaService
from graph_rag.domain.ids import new_id
from graph_rag.domain.quotas.models import QuotaMetric
from graph_rag.infrastructure.persistence.postgres.models.abac import (
    QuotaAssignmentModel,
    QuotaPlanModel,
)
from graph_rag.infrastructure.persistence.postgres.models.documents import (
    DocumentModel,
    TenantModel,
)
from graph_rag.infrastructure.persistence.postgres.models.users import UserModel
from graph_rag.shared.exceptions import QuotaExceededError

ADMIN_DSN = "postgresql+asyncpg://enterprise_rag:change-me@127.0.0.1:5433/enterprise_rag"
DB_NAME = "upload_quota_test"
TEST_DSN = f"postgresql+asyncpg://enterprise_rag:change-me@127.0.0.1:5433/{DB_NAME}"


async def _admin(sql: str) -> None:
    engine = create_async_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        if sql.startswith("DROP DATABASE"):
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": DB_NAME},
            )
        await conn.execute(text(sql))
    await engine.dispose()


async def _seed() -> tuple[object, object]:
    tenant_id = new_id()
    user_id = new_id()
    engine = create_async_engine(TEST_DSN)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        session.add(
            TenantModel(
                tenant_id=tenant_id,
                tenant_key=f"quota-{tenant_id.hex[:8]}",
                display_name="Quota",
                is_active=True,
                metadata_json={},
            )
        )
        session.add(
            UserModel(
                user_id=user_id,
                tenant_id=tenant_id,
                email=f"{user_id.hex}@example.test",
                password_hash="not-a-secret",
                role="member",
                status="active",
                is_active=True,
                attributes={},
            )
        )
        await session.flush()
        plan_id = new_id()
        session.add(
            QuotaPlanModel(
                plan_id=plan_id,
                name=f"tight-{plan_id.hex[:8]}",
                limits={"documents:month": 1, "storage_bytes:month": 100},
                metadata_json={},
            )
        )
        await session.flush()
        session.add(
            QuotaAssignmentModel(
                assignment_id=new_id(),
                tenant_id=tenant_id,
                user_id=None,
                plan_id=plan_id,
                period="month",
                overrides={},
                is_active=True,
            )
        )
        session.add(
            QuotaAssignmentModel(
                assignment_id=new_id(),
                tenant_id=tenant_id,
                user_id=user_id,
                plan_id=plan_id,
                period="month",
                overrides={},
                is_active=True,
            )
        )
        await session.commit()
        documents = await session.scalar(select(func.count()).select_from(DocumentModel))
    await engine.dispose()
    assert documents == 0
    return tenant_id, user_id


async def _reserve_pair(tenant_id, user_id, metric: QuotaMetric, quantity: int) -> list[object]:
    engine = create_async_engine(TEST_DSN)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = PostgresQuotaService(factory)
    barrier = asyncio.Barrier(2)

    async def once() -> object:
        await barrier.wait()
        return await service.reserve(
            tenant_id=tenant_id,
            user_id=user_id,
            metric=metric,
            quantity=quantity,
        )

    results = await asyncio.gather(once(), once(), return_exceptions=True)
    await engine.dispose()
    return list(results)


def _assert_one_refusal(results: list[object], quota: str) -> None:
    successes = [item for item in results if not isinstance(item, Exception)]
    failures = [item for item in results if isinstance(item, QuotaExceededError)]
    assert len(successes) == 1
    assert len(failures) == 1
    details = failures[0].details
    assert set(details) >= {"quota", "limit", "used", "remaining", "reset_at"}
    assert details["quota"] == quota


@pytest.mark.integration
def test_concurrent_reserves_share_one_budget(compose_postgres: str) -> None:
    _ = compose_postgres
    asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{DB_NAME}"'))
    asyncio.run(_admin(f'CREATE DATABASE "{DB_NAME}"'))
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DSN)
    try:
        command.upgrade(cfg, "head")
        tenant_id, user_id = asyncio.run(_seed())
        documents = asyncio.run(
            _reserve_pair(tenant_id, user_id, QuotaMetric.DOCUMENTS, 1)
        )
        _assert_one_refusal(documents, "documents")
        storage = asyncio.run(
            _reserve_pair(tenant_id, user_id, QuotaMetric.STORAGE_BYTES, 60)
        )
        _assert_one_refusal(storage, "storage_bytes")
    finally:
        asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{DB_NAME}"'))
