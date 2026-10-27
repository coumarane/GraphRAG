"""Upgrade and downgrade 0013 against local Compose Postgres."""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ADMIN_DSN = "postgresql+asyncpg://enterprise_rag:change-me@127.0.0.1:5433/enterprise_rag"
TEST_DB = "upload_migration_0013"
TEST_DSN = f"postgresql+asyncpg://enterprise_rag:change-me@127.0.0.1:5433/{TEST_DB}"


async def _admin(sql: str) -> None:
    engine = create_async_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(sql))
    await engine.dispose()


async def _count(table: str) -> int:
    statements = {
        "documents": text("SELECT count(*) FROM documents"),
        "ingestion_runs": text("SELECT count(*) FROM ingestion_runs"),
    }
    engine = create_async_engine(TEST_DSN)
    async with engine.connect() as conn:
        value = (await conn.execute(statements[table])).scalar_one()
    await engine.dispose()
    return int(value)


async def _columns() -> tuple[set[str], set[str]]:
    engine = create_async_engine(TEST_DSN)
    async with engine.connect() as conn:
        tables = set((await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ))).scalars())
        columns = set((await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'document_versions'"
        ))).scalars())
    await engine.dispose()
    return tables, columns


@pytest.mark.integration
def test_upgrade_and_downgrade_keep_existing_documents(compose_postgres: str) -> None:
    _ = compose_postgres
    asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{TEST_DB}"'))
    asyncio.run(_admin(f'CREATE DATABASE "{TEST_DB}"'))
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DSN)
    try:
        command.upgrade(cfg, "0012_document_search")
        before_tables, _ = asyncio.run(_columns())
        before_documents = asyncio.run(_count("documents"))
        before_runs = asyncio.run(_count("ingestion_runs"))
        command.upgrade(cfg, "head")
        tables, columns = asyncio.run(_columns())
        assert "upload_sessions" in tables
        assert "documents" in before_tables
        assert asyncio.run(_count("documents")) == before_documents
        assert asyncio.run(_count("ingestion_runs")) == before_runs
        assert "etag" in columns
        assert "object_version_id" in columns
        command.downgrade(cfg, "0012_document_search")
        tables, columns = asyncio.run(_columns())
        assert "upload_sessions" not in tables
        assert "documents" in tables
        assert asyncio.run(_count("documents")) == before_documents
        assert asyncio.run(_count("ingestion_runs")) == before_runs
        assert "etag" not in columns
    finally:
        asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{TEST_DB}"'))
