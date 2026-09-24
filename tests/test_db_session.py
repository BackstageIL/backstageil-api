import asyncio

import pytest

from app.core.config import Settings
from app.db.session import Database, build_engine_args


def test_neon_url_is_converted_for_asyncpg() -> None:
    url = "postgresql://user:pw@ep-x.eu-central-1.aws.neon.tech/app?sslmode=require&channel_binding=require"

    clean_url, connect_args = build_engine_args(url)

    assert clean_url == "postgresql+asyncpg://user:pw@ep-x.eu-central-1.aws.neon.tech/app"
    assert connect_args == {"ssl": True}


def test_local_url_without_ssl_keeps_other_params() -> None:
    clean_url, connect_args = build_engine_args(
        "postgres://u:p@localhost:5432/db?application_name=api"
    )

    assert clean_url == "postgresql+asyncpg://u:p@localhost:5432/db?application_name=api"
    assert connect_args == {}


def test_sslmode_disable_does_not_force_ssl() -> None:
    _, connect_args = build_engine_args("postgresql://u:p@localhost/db?sslmode=disable")

    assert connect_args == {}


def test_empty_database_url_means_no_database() -> None:
    settings = Settings(_env_file=None, database_url="")

    assert settings.database_url is None


def test_real_database_is_reachable() -> None:
    """Integration test: runs only when DATABASE_URL is set (local .env or the CI secret)."""
    database_url = Settings().database_url
    if database_url is None:
        pytest.skip("DATABASE_URL not set")

    async def ping() -> None:
        database = Database(database_url.get_secret_value())
        try:
            await database.ping()
        finally:
            await database.dispose()

    asyncio.run(ping())
