"""Integration: API-key rotation rehearsal, zero downtime (M5-5 acceptance).

Follows ops/runbooks/secrets-rotation.md exactly: overlap window with both
keys valid, client rollover, then revocation of the old key.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

from neuralgram.api.app import create_app
from neuralgram.common.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]

OLD_KEY = "rotation-old-key"  # pragma: allowlist secret
NEW_KEY = "rotation-new-key"  # pragma: allowlist secret
TENANT = "tenant-rotate"


@pytest.fixture(scope="module")
def async_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=os.environ | {"DATABASE_URL": url},
            capture_output=True,
            text=True,
        )
        assert upgrade.returncode == 0, upgrade.stderr
        yield url


def _client(async_url: str, vault: Path, keys: dict[str, str]) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                _env_file=None,
                database_url=async_url,
                vault_path=str(vault),
                api_keys=keys,
            )
        )
    )


def _search_status(client: TestClient, key: str) -> int:
    return client.get(
        "/memory/search", params={"q": "rotation"}, headers={"x-api-key": key}
    ).status_code


def test_key_rotation_rehearsal(async_url: str, tmp_path: Path) -> None:
    # Phase 1: only the old key exists.
    with _client(async_url, tmp_path, {OLD_KEY: TENANT}) as client:
        assert _search_status(client, OLD_KEY) == 200
        assert _search_status(client, NEW_KEY) == 401

    # Phase 2: overlap window — both keys serve the same tenant, no downtime.
    with _client(async_url, tmp_path, {OLD_KEY: TENANT, NEW_KEY: TENANT}) as client:
        assert _search_status(client, OLD_KEY) == 200
        assert _search_status(client, NEW_KEY) == 200

    # Phase 3: old key revoked — new key keeps serving.
    with _client(async_url, tmp_path, {NEW_KEY: TENANT}) as client:
        assert _search_status(client, OLD_KEY) == 401
        assert _search_status(client, NEW_KEY) == 200
