"""Integration: the demo tenant is capped at 3 messages per ingest call (M6)."""

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

DEMO_KEY = "test-demo-key"  # pragma: allowlist secret
DEMO_TENANT = "test-demo-tenant"
OTHER_KEY = "test-other-key"  # pragma: allowlist secret
OTHER_TENANT = "test-other-tenant"


def _messages(count: int) -> dict[str, object]:
    return {
        "messages": [
            {"user": "alice", "text": f"message {i}", "ts": f"{1700000000 + i}.000000"}
            for i in range(count)
        ]
    }


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
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

        settings = Settings(
            _env_file=None,
            database_url=url,
            vault_path=str(tmp_path_factory.mktemp("vault")),
            api_keys={DEMO_KEY: DEMO_TENANT, OTHER_KEY: OTHER_TENANT},
            demo_tenant_id=DEMO_TENANT,
        )
        with TestClient(create_app(settings)) as test_client:
            yield test_client


def test_demo_tenant_over_limit_is_422(client: TestClient) -> None:
    response = client.post(
        "/memory/ingest",
        json={"source_id": "demo-src", "payload": _messages(4)},
        headers={"x-api-key": DEMO_KEY},
    )
    assert response.status_code == 422, response.text


def test_demo_tenant_at_limit_succeeds(client: TestClient) -> None:
    response = client.post(
        "/memory/ingest",
        json={"source_id": "demo-src-2", "payload": _messages(3)},
        headers={"x-api-key": DEMO_KEY},
    )
    assert response.status_code == 200, response.text


def test_other_tenant_unaffected_by_demo_limit(client: TestClient) -> None:
    response = client.post(
        "/memory/ingest",
        json={"source_id": "other-src", "payload": _messages(4)},
        headers={"x-api-key": OTHER_KEY},
    )
    assert response.status_code == 200, response.text
