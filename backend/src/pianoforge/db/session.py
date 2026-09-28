"""Engines and session factories.

The API uses the async engine; Celery workers use the sync engine. Both use the
psycopg 3 driver, so a single ``postgresql+psycopg://`` URL serves both.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from pianoforge.config import get_settings


@lru_cache(maxsize=1)
def get_async_engine() -> AsyncEngine:
    s = get_settings()
    return create_async_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_async_engine(), expire_on_commit=False)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with get_async_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@lru_cache(maxsize=1)
def get_sync_engine() -> Engine:
    s = get_settings()
    # Workers are prefork processes with low concurrency; keep the pool small.
    return create_engine(s.database_url, pool_size=2, max_overflow=2, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_sync_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(get_sync_engine(), expire_on_commit=False)


@contextmanager
def sync_session() -> Iterator[Session]:
    """Worker helper: commit on success, roll back on error."""
    session = get_sync_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engines_after_fork() -> None:
    """Called in each forked Celery child so connections are not shared across processes."""
    if get_sync_engine.cache_info().currsize:
        get_sync_engine().dispose(close=False)
    get_sync_engine.cache_clear()
    get_sync_sessionmaker.cache_clear()
