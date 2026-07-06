"""Unit tests: secrets are loadable from a mounted secrets directory (M5-5)."""

import json
from pathlib import Path

import pytest

from neuralgram.common.config import Settings, get_settings


def test_secrets_dir_files_override_defaults(tmp_path: Path) -> None:
    (tmp_path / "api_keys").write_text(json.dumps({"file-key": "tenant-file"}))
    (tmp_path / "redis_url").write_text("redis://secret-host:6379/0")

    settings = Settings(_env_file=None, _secrets_dir=str(tmp_path))
    assert settings.api_keys == {"file-key": "tenant-file"}
    assert settings.redis_url == "redis://secret-host:6379/0"
    assert settings.mock_providers is True, "non-secret defaults still apply"


def test_get_settings_honors_secrets_dir_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "api_keys").write_text(json.dumps({"env-dir-key": "tenant-env"}))
    monkeypatch.setenv("NEURALGRAM_SECRETS_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        assert get_settings().api_keys == {"env-dir-key": "tenant-env"}
    finally:
        get_settings.cache_clear()


def test_missing_secrets_dir_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEURALGRAM_SECRETS_DIR", "/does/not/exist")
    get_settings.cache_clear()
    try:
        assert get_settings().mock_providers is True
    finally:
        get_settings.cache_clear()
