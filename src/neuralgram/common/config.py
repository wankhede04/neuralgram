"""Typed application settings, sourced from the environment (standards §3)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DB_CREDENTIALS = "neuralgram:neuralgram"  # pragma: allowlist secret


class Settings(BaseSettings):
    """All runtime configuration for Neuralgram.

    Values come from environment variables (case-insensitive) or an
    optional local `.env` file. Defaults are safe for dev/CI: mock
    providers are ON, so no real model-provider keys are required.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "dev"
    log_level: str = "INFO"

    mock_providers: bool = True
    embedding_dim: int = 384

    database_url: str = f"postgresql+asyncpg://{_DEV_DB_CREDENTIALS}@localhost:5432/neuralgram"
    redis_url: str = "redis://localhost:6379/0"
    vault_path: str = "./vault"

    # Maps API key -> tenant_id (ADR-0006). Empty by default: no key, no access.
    api_keys: dict[str, str] = {}


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide `Settings` instance (cached after first read)."""
    return Settings()
