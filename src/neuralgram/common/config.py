"""Typed application settings, sourced from the environment (standards §3)."""

import os
from functools import lru_cache
from pathlib import Path

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

    # Real completion provider (M4-2). Anthropic has no embeddings API, so
    # `hint:embed` routes to OpenRouter (OpenAI-compatible /embeddings) below.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # Real embedding provider, routed via OpenRouter's OpenAI-compatible API.
    openrouter_api_key: str = ""
    # Must output 384 dims to match storage.models.EMBEDDING_DIM (pgvector
    # column is fixed-width); the :free NVIDIA models output 2048 and don't fit.
    openrouter_embedding_model: str = "sentence-transformers/all-minilm-l6-v2"

    database_url: str = f"postgresql+asyncpg://{_DEV_DB_CREDENTIALS}@localhost:5432/neuralgram"
    redis_url: str = "redis://localhost:6379/0"
    vault_path: str = "./vault"

    # Maps API key -> tenant_id (ADR-0006). Empty by default: no key, no access.
    api_keys: dict[str, str] = {}

    # Maps API key -> role (reader|writer|admin); absent keys default to writer (M5-2).
    api_key_roles: dict[str, str] = {}

    # High budget: deterministic clean-up only on ingest; no lossy truncation.
    ingest_compress_budget_tokens: int = 100_000

    # Hard per-tenant spend caps in USD (env TENANT_SPEND_CAPS, JSON). No entry = no cap.
    tenant_spend_caps: dict[str, float] = {}

    cache_ttl_seconds: int = 3600


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide `Settings` instance (cached after first read).

    When `NEURALGRAM_SECRETS_DIR` names an existing directory (a mounted
    secret-manager volume, e.g. /run/secrets), files in it override env
    values — secrets never need to live in env files or the repo (M5-5).
    """
    secrets_dir = os.getenv("NEURALGRAM_SECRETS_DIR")
    if secrets_dir and Path(secrets_dir).is_dir():
        return Settings(_secrets_dir=secrets_dir)  # type: ignore[call-arg]  # pydantic-settings kwarg
    return Settings()
