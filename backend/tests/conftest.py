"""
Shared pytest fixtures.

Most tests run against an in-memory SQLite database (via aiosqlite), so they
need no DB setup and leave no data behind. Only tables that work on SQLite
are created there.

Tests that need real PostgreSQL features (ARRAY, JSONB, ON CONFLICT) use the
`pg_sessionmaker` fixture, which requires TEST_DATABASE_URL to point at an
EMPTY, disposable database (all tables are dropped afterwards), e.g.
    TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:5433/investment_copilot_test
Without it, those tests are skipped.
"""

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base, BrokerConnection, PortfolioHolding, RefreshToken, Transaction, User

SQLITE_TABLES = [
    User.__table__,
    RefreshToken.__table__,
    PortfolioHolding.__table__,
    Transaction.__table__,
    BrokerConnection.__table__,
]


@pytest.fixture
async def db_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # StaticPool = one shared connection, so every session sees the same in-memory DB.
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=SQLITE_TABLES)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def pg_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set (needs a disposable PostgreSQL database)")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _client_for(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    """HTTP client that calls the FastAPI app in-process, with get_db pointed at `session_factory`."""

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def client(db_sessionmaker) -> AsyncIterator[AsyncClient]:
    """API client backed by in-memory SQLite."""
    async for ac in _client_for(db_sessionmaker):
        yield ac


@pytest.fixture
async def pg_client(pg_sessionmaker) -> AsyncIterator[AsyncClient]:
    """API client backed by the disposable PostgreSQL test DB (skipped without TEST_DATABASE_URL)."""
    async for ac in _client_for(pg_sessionmaker):
        yield ac


async def signup_headers(client: AsyncClient, email: str = "user@example.com") -> dict[str, str]:
    """Create a user through the API and return its Authorization header."""
    r = await client.post("/auth/signup", json={"email": email, "password": "password-123"})
    assert r.status_code == 201, r.text
    client.cookies.clear()  # keep each test user's refresh cookie out of later requests
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
