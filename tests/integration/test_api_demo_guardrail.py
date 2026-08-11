"""Integration: the demo tenant is capped at 3 messages per ingest call (M6)."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

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
    with (
        PostgresContainer("pgvector/pgvector:pg16") as pg,
        RedisContainer("redis:7-alpine") as redis,
    ):
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=os.environ | {"DATABASE_URL": url},
            capture_output=True,
            text=True,
        )
        assert upgrade.returncode == 0, upgrade.stderr

        redis_host = redis.get_container_host_ip()
        redis_port = redis.get_exposed_port(6379)

        settings = Settings(
            _env_file=None,
            database_url=url,
            redis_url=f"redis://{redis_host}:{redis_port}/0",
            vault_path=str(tmp_path_factory.mktemp("vault")),
            api_keys={DEMO_KEY: DEMO_TENANT, OTHER_KEY: OTHER_TENANT},
            demo_tenant_id=DEMO_TENANT,
            demo_ip_daily_limit=3,
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


def test_demo_ip_rate_limit_blocks_after_daily_cap(client: TestClient) -> None:
    # The two demo-tenant tests above already made 2 requests from this
    # client's IP; demo_ip_daily_limit=3, so one more is still allowed...
    third = client.post(
        "/memory/ingest",
        json={"source_id": "demo-src-3", "payload": _messages(1)},
        headers={"x-api-key": DEMO_KEY},
    )
    assert third.status_code == 200, third.text

    # ...and the next request from the same IP is rate-limited, regardless
    # of message count.
    fourth = client.post(
        "/memory/ingest",
        json={"source_id": "demo-src-4", "payload": _messages(1)},
        headers={"x-api-key": DEMO_KEY},
    )
    assert fourth.status_code == 429, fourth.text
    assert "demo" in fourth.json()["detail"].lower()


def test_demo_visitors_on_different_ips_get_isolated_data(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    with (
        PostgresContainer("pgvector/pgvector:pg16") as pg,
        RedisContainer("redis:7-alpine") as redis,
    ):
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql+asyncpg://")
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
            redis_url=f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0",
            vault_path=str(tmp_path_factory.mktemp("vault-iso")),
            api_keys={DEMO_KEY: DEMO_TENANT},
            demo_tenant_id=DEMO_TENANT,
            demo_ip_daily_limit=10,
        )
        app = create_app(settings)

        with TestClient(app, client=("1.1.1.1", 12345)) as visitor_a:
            ingested = visitor_a.post(
                "/memory/ingest",
                json={"source_id": "iso-src-a", "payload": _messages(1)},
                headers={"x-api-key": DEMO_KEY},
            )
            assert ingested.status_code == 200, ingested.text

        with TestClient(app, client=("2.2.2.2", 12345)) as visitor_b:
            found_own = visitor_b.get(
                "/memory/search",
                params={"q": "message", "mode": "keyword"},
                headers={"x-api-key": DEMO_KEY},
            )
            assert found_own.status_code == 200, found_own.text
            assert found_own.json() == [], (
                "a fresh visitor IP must not see another visitor's demo data"
            )

        with TestClient(app, client=("1.1.1.1", 12345)) as visitor_a_again:
            found_again = visitor_a_again.get(
                "/memory/search",
                params={"q": "message", "mode": "keyword"},
                headers={"x-api-key": DEMO_KEY},
            )
            assert found_again.status_code == 200, found_again.text
            assert len(found_again.json()) >= 1, (
                "the same visitor IP must still see its own previously ingested data"
            )
