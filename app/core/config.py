"""Application settings, read from environment variables (and a local, git-ignored `.env`)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "ci", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # PostgreSQL URL (Neon). Optional: the app starts without a database and /health/ready says so.
    database_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=5, ge=0, le=20)

    # Browser origins allowed to call the API, e.g. CORS_ORIGINS='["https://backstageil.com"]'
    cors_origins: list[str] = []

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_database_url_is_unset(cls, value: object) -> object:
        # `DATABASE_URL=` (as in .env.example) means "no database", not an empty URL.
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
