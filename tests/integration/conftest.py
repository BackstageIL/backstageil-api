"""
Integration tests against a real PostgreSQL (Neon `dev` locally, Neon `ci` in CI).

Skipped when DATABASE_URL is not set. The schema must be migrated (`alembic upgrade head`).
Every test runs inside a transaction that is rolled back, so nothing is left in the database.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import Database


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
async def database() -> AsyncIterator[Database]:
    """One engine for the whole run (Neon is remote: opening a connection per test is slow)."""
    database_url = Settings().database_url
    if database_url is None:
        pytest.skip("DATABASE_URL not set")
    db = Database(database_url.get_secret_value(), pool_size=1, max_overflow=0)
    try:
        yield db
    finally:
        await db.dispose()


@pytest.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.engine.connect() as connection:
        transaction = await connection.begin()
        db_session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield db_session
        finally:
            await db_session.close()
            await transaction.rollback()
