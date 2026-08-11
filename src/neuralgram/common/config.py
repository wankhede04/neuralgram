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
    # `hint:embed` routes elsewhere -- see jina_api_key/openrouter_api_key.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # Real embedding provider. Checked first: Jina AI's own API (native
    # `dimensions` truncation, no OpenAI-compatible base_url needed). Falls
    # back to OpenRouter if unset, then to the mock provider if neither key
    # is configured.
    jina_api_key: str = ""
    jina_embedding_model: str = "jina-embeddings-v3"

    # Fallback embedding provider, routed via OpenRouter's OpenAI-compatible
    # API, used only when jina_api_key is unset.
    openrouter_api_key: str = ""
    # Must output 384 dims to match storage.models.EMBEDDING_DIM (pgvector
    # column is fixed-width); the :free NVIDIA models output 2048 and don't fit.
    openrouter_embedding_model: str = "sentence-transformers/all-minilm-l6-v2"

    database_url: str = f"postgresql+asyncpg://{_DEV_DB_CREDENTIALS}@localhost:5432/neuralgram"
    redis_url: str = "redis://localhost:6379/0"
    vault_path: str = "./vault"

    # If set, POST /memory/ingest caps this exact tenant to 3 messages per
    # call (frontend/, M6 unauthenticated demo page). No effect on any
    # other tenant.
    demo_tenant_id: str = ""

    # Per-IP daily request cap for the unauthenticated demo tenant, enforced
    # via Redis (ADR-needed: protects API cost from a single shared demo key
    # otherwise being callable without limit). No effect on signed-up/static
    # tenants.
    demo_ip_daily_limit: int = 8

    # Aggregate USD cap shared across every demo visitor combined (all
    # per-IP demo tenants together), since the per-IP daily request count
    # alone bounds request count, not AI spend, and an exact-match entry in
    # `tenant_spend_caps` can never match a per-IP-suffixed demo tenant_id.
    # No value (0) = no cap.
    demo_spend_cap_usd: float = 0.0

    # Maps API key -> tenant_id (ADR-0006). Empty by default: no key, no access.
    api_keys: dict[str, str] = {}

    # Maps API key -> role (reader|writer|admin); absent keys default to writer (M5-2).
    api_key_roles: dict[str, str] = {}

    # High budget: deterministic clean-up only on ingest; no lossy truncation.
    ingest_compress_budget_tokens: int = 100_000

    # Hard per-tenant spend caps in USD (env TENANT_SPEND_CAPS, JSON). No entry = no cap.
    tenant_spend_caps: dict[str, float] = {}

    # Lifetime cap on real provider calls for self-serve signup tenants
    # (users-table rows) -- 3 completion calls + 3 embed calls, tracked
    # independently via existing usage_events rows, no reset (M7).
    signup_call_limit: int = 3

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
