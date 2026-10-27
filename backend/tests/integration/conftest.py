"""Compose-backed fixtures. Tests skip when Docker services are not reachable."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from graph_rag.infrastructure.persistence.postgres.base import Base
from graph_rag.infrastructure.persistence.postgres.models.uploads import (
    UploadSessionModel,  # noqa: F401
)


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


@pytest.fixture
def compose_postgres() -> str:
    if not _port_open(5433):
        pytest.skip("Compose Postgres is not listening on 127.0.0.1:5433")
    return "postgresql+asyncpg://enterprise_rag:change-me@127.0.0.1:5433/enterprise_rag"


@pytest.fixture
def compose_redis() -> str:
    """Isolated Compose Redis. Host 6379 belongs to other local projects and is never used."""
    if not _port_open(6380):
        pytest.skip(
            "Isolated Compose Redis is not listening on 127.0.0.1:6380"
        )
    return "redis://127.0.0.1:6380/0"


@pytest.fixture
def compose_minio() -> None:
    if not _port_open(9000):
        pytest.skip("Compose MinIO is not listening on 127.0.0.1:9000")
