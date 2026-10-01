"""
Async database engine and session factory (SQLAlchemy 2 + asyncpg).

Neon gives a libpq-style URL (postgresql://...?sslmode=require&channel_binding=require).
SQLAlchemy's async engine needs the postgresql+asyncpg:// scheme, and asyncpg does not accept
libpq SSL query parameters, so they are stripped and SSL is passed as a connect argument instead.
"""

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_LIBPQ_ONLY_PARAMS = {
    "sslmode",
    "sslcert",
    "sslkey",
    "sslrootcert",
    "sslcrl",
    "channel_binding",
}
_SSL_REQUIRED_MODES = {"require", "verify-ca", "verify-full"}


def build_engine_args(url: str) -> tuple[str, dict[str, Any]]:
    """Return (asyncpg URL, connect_args) for create_async_engine from a libpq-style URL."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"

    params = parse_qsl(parts.query, keep_blank_values=True)
    ssl_required = any(k == "sslmode" and v.lower() in _SSL_REQUIRED_MODES for k, v in params)
    kept = [(k, v) for k, v in params if k not in _LIBPQ_ONLY_PARAMS]

    clean_url = urlunsplit(parts._replace(scheme=scheme, query=urlencode(kept)))
    connect_args: dict[str, Any] = {"ssl": True} if ssl_required else {}
    return clean_url, connect_args


class Database:
    """Owns the engine and session factory for the application's lifetime.

    pooled=True is for a connection pooler in front of Postgres (Neon's `-pooler` endpoint, used
    on serverless hosts): asyncpg's prepared-statement caches are turned off so the app never
    depends on the pooler routing a statement back to the same server connection. Verified to work
    both ways against Neon (2026-10); off is a cheap safety net.
    """

    def __init__(
        self, url: str, *, pool_size: int = 5, max_overflow: int = 5, pooled: bool = False
    ) -> None:
        clean_url, connect_args = build_engine_args(url)
        if pooled:
            connect_args |= {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
        self.connect_args = connect_args
        self.engine: AsyncEngine = create_async_engine(
            clean_url,
            connect_args=connect_args,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
        )
        self.sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def ping(self) -> None:
        """Raise if the database cannot be reached."""
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
