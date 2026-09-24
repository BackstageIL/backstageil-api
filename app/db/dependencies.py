"""FastAPI dependencies for database access."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DatabaseNotConfiguredError
from app.db.session import Database


def get_database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise DatabaseNotConfiguredError()
    return database


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async with database.sessionmaker() as session:
        yield session
