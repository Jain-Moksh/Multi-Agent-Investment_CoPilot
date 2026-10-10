"""
Async database engine and session factory.

Routes get a session through the `get_db` dependency:

    async def endpoint(db: AsyncSession = Depends(get_db)): ...
"""

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

# The engine is lazy: no connection is opened until the first query.
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,               # drop dead connections from the pool transparently
    connect_args={"timeout": 5},      # asyncpg connect timeout (s); fail fast if DB is down
)

# expire_on_commit=False lets us keep using objects after commit (common in async code).
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, closed automatically afterwards."""
    async with AsyncSessionLocal() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    FastAPI dependency for routes that start agents / background-style work needing
    several independent sessions (agents open their own). Overridden in tests, like get_db.
    """
    return AsyncSessionLocal


async def check_db_connection() -> tuple[bool, str | None]:
    """
    Run `SELECT 1` against the database.
    Returns (True, None) when reachable, else (False, short error description).
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # any failure (refused, bad password, missing DB) = unhealthy
        logger.warning("Database connectivity check failed: %r", exc)
        return False, type(exc).__name__
