"""Unit tests for typed settings and mock mode (P0-4 acceptance)."""

import pytest

from neuralgram.api.app import create_app
from neuralgram.common.config import Settings


def test_defaults_are_key_free_and_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("MOCK_PROVIDERS", "DATABASE_URL", "REDIS_URL", "EMBEDDING_DIM"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)
    assert settings.mock_providers is True
    assert settings.environment == "dev"
    assert settings.embedding_dim == 384


def test_env_overrides_are_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_PROVIDERS", "false")
    monkeypatch.setenv("EMBEDDING_DIM", "16")
    monkeypatch.setenv("ENVIRONMENT", "prod")
    settings = Settings(_env_file=None)
    assert settings.mock_providers is False
    assert settings.embedding_dim == 16
    assert settings.environment == "prod"


def test_app_starts_with_no_real_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    app = create_app(Settings(_env_file=None))
    assert app.state.settings.mock_providers is True
