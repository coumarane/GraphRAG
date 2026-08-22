"""Engine and session factories for async SQLAlchemy."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from graph_rag.config.settings import PostgresSettings


def create_engine(settings: PostgresSettings, *, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine from settings."""
    return create_async_engine(
        settings.async_dsn,
        echo=echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=True,
    )


def create_engine_from_url(url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine from an explicit URL (tests / Alembic)."""
    return create_async_engine(url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build a session factory with expire_on_commit disabled for domain mapping."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class LockedAsyncProxy:
    """Serializes coroutine-method calls on a wrapped object via a shared lock.

    The API and worker processes each hold a single AsyncSession for their
    whole lifetime rather than one per request/task, but AsyncSession is not
    safe for concurrent use by multiple coroutines: interleaved awaits on the
    same session corrupt its internal state (surfaces as asyncpg
    'InterfaceError: another operation is in progress' or SQLAlchemy
    'InvalidRequestError: session is in ... state'), breaking whichever call
    happens to run next regardless of which one was "at fault".

    Wrapping the raw session alone isn't enough: repositories call session
    methods like `add()` synchronously (no `await`), so a lock that only
    guards `await session.xxx()` calls still lets a concurrent `add()` land
    in the middle of another coroutine's in-flight flush/commit. Instead,
    wrap each repository (whose public methods are all coroutines covering
    one complete unit of work — e.g. add + flush) with this proxy, sharing
    one lock across all repositories and the session itself. Pass the *raw*
    session into repository constructors so their internal session calls
    don't try to re-acquire the same lock their own method call already
    holds (asyncio.Lock is not reentrant).

    This only guards call boundaries against overlapping in-flight
    operations; it does not give each caller its own transaction. Concurrent
    callers still share one transaction/session state, same as before this
    wrapper existed.
    """

    def __init__(self, target: Any, lock: asyncio.Lock) -> None:
        self._target = target
        self._lock = lock

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._target, name)
        if not asyncio.iscoroutinefunction(attr):
            return attr

        async def _locked(*args: Any, **kwargs: Any) -> Any:
            async with self._lock:
                return await attr(*args, **kwargs)

        return _locked


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a session and commit/rollback explicitly."""
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
