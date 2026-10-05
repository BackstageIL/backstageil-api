"""Application settings, read from environment variables (and a local, git-ignored `.env`)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "ci", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # PostgreSQL URL (Neon). Optional: the app starts without a database and /health/ready says so.
    database_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=5, ge=0, le=20)
    # True when DATABASE_URL is a connection-pooler endpoint (Neon "-pooler", serverless hosts):
    # small per-instance pool and no client-side prepared-statement caches.
    db_pooled: bool = False

    # Browser origins allowed to call the API, e.g. CORS_ORIGINS='["https://backstageil.com"]'
    cors_origins: list[str] = []

    # Salted scrypt hash of the admin API key ("scrypt$n$r$p$salt$hash"); the key itself is never
    # stored. Unset = admin disabled. Generate with: uv run python -m scripts.new_admin_key
    admin_api_key_hash: str | None = Field(
        default=None, pattern=r"^scrypt\$\d+\$\d+\$\d+\$[A-Za-z0-9_-]+\$[A-Za-z0-9_-]+$"
    )
    # Wrong admin keys allowed per client address within the window before answering 429
    admin_max_failed_attempts: int = Field(default=10, ge=1)
    admin_failed_window_seconds: int = Field(default=300, ge=1)

    # Sentry project DSN for error tracking (BSIL-28). Unset = no error reports are sent.
    sentry_dsn: SecretStr | None = None

    # Vercel Blob store for hall pictures (BSIL-24); Vercel sets it when the store is connected
    # to the project. Unset = uploads disabled.
    blob_read_write_token: SecretStr | None = None
    # Optional override of the public base URL of picture files (default: the store's own URL)
    pictures_base_url: HttpUrl | None = None

    @field_validator(
        "database_url",
        "admin_api_key_hash",
        "sentry_dsn",
        "blob_read_write_token",
        "pictures_base_url",
        mode="before",
    )
    @classmethod
    def empty_value_is_unset(cls, value: object) -> object:
        # `DATABASE_URL=` (as in .env.example) means "not set", not an empty value.
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
