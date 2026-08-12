"""CORS: the browser dashboard's origin must be allowed (frontend/, M6)."""

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


def test_preflight_allows_dashboard_origin() -> None:
    # Preflight OPTIONS is handled entirely by CORSMiddleware before any
    # route/dependency runs, so no database access happens here.
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.options(
            "/memory/search",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "x-api-key" in allowed_headers


def test_cors_allowed_origins_is_configurable() -> None:
    """A deployed frontend origin (e.g. a Vercel URL) must be addable via
    config, not hardcoded -- CORS_ALLOWED_ORIGINS overrides the dev default."""
    settings = Settings(
        _env_file=None,
        cors_allowed_origins=["https://neuralgram.vercel.app", "http://localhost:5173"],
    )
    with TestClient(create_app(settings)) as client:
        response = client.options(
            "/memory/search",
            headers={
                "Origin": "https://neuralgram.vercel.app",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "https://neuralgram.vercel.app"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    # An unrecognized x-api-key falls through to the DB-backed auth tier
    # (deps.py's _resolve_db), which needs a real, migrated Postgres --
    # unlike the preflight test above, this one can't run against no DB.
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
        )
        with TestClient(create_app(settings)) as test_client:
            yield test_client


def test_actual_request_carries_cors_header(client: TestClient) -> None:
    response = client.get(
        "/memory/search",
        params={"q": "x"},
        headers={"Origin": "http://localhost:5173", "x-api-key": "no-such-key"},
    )
    # 401 (bad key) is expected here -- we're only checking the CORS header is present
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
