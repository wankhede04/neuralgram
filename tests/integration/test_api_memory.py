"""Integration: memory API end-to-end with auth + tenant scoping (M1-7 acceptance)."""

import json
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
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "slack_export_sample.json"

KEY_A = "test-key-tenant-a"  # pragma: allowlist secret
KEY_B = "test-key-tenant-b"  # pragma: allowlist secret


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
            api_keys={KEY_A: "tenant-a", KEY_B: "tenant-b"},
        )
        with TestClient(create_app(settings)) as test_client:
            yield test_client


def _ingest(client: TestClient, key: str) -> dict[str, int]:
    response = client.post(
        "/memory/ingest",
        json={"source_id": "C042MEMORY", "payload": json.loads(FIXTURE.read_text())},
        headers={"x-api-key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_ingest_search_fetch_roundtrip(client: TestClient) -> None:
    first = _ingest(client, KEY_A)
    assert first["documents"] == 2
    assert first["chunks_inserted"] > 0

    search = client.get(
        "/memory/search", params={"q": "migration checklist"}, headers={"x-api-key": KEY_A}
    )
    assert search.status_code == 200
    hits = search.json()
    assert hits and "migration checklist" in hits[0]["content_md"]
    assert hits[0]["provenance"]["author"] == "U01ALICE"

    chunk_id = hits[0]["chunk_id"]
    fetched = client.get(f"/memory/chunks/{chunk_id}", headers={"x-api-key": KEY_A})
    assert fetched.status_code == 200
    assert fetched.json()["provenance"]["source_type"] == "slack"


def test_reingest_is_idempotent_via_api(client: TestClient) -> None:
    _ingest(client, KEY_A)
    again = _ingest(client, KEY_A)
    assert again["chunks_inserted"] == 0
    assert again["chunks_skipped"] > 0


def test_tenant_b_cannot_see_tenant_a_data(client: TestClient) -> None:
    _ingest(client, KEY_A)
    search = client.get(
        "/memory/search", params={"q": "migration checklist"}, headers={"x-api-key": KEY_B}
    )
    assert search.status_code == 200
    assert search.json() == []

    mine = client.get(
        "/memory/search", params={"q": "migration checklist"}, headers={"x-api-key": KEY_A}
    ).json()
    foreign_fetch = client.get(
        f"/memory/chunks/{mine[0]['chunk_id']}", headers={"x-api-key": KEY_B}
    )
    assert foreign_fetch.status_code == 404


def test_compression_metrics_visible_after_real_ingest(client: TestClient) -> None:
    _ingest(client, KEY_A)
    metrics_text = client.get("/metrics").text
    assert 'neuralgram_compression_tokens_in_total{rule="builtin:' in metrics_text
    assert 'neuralgram_compression_tokens_out_total{rule="builtin:' in metrics_text
    assert "neuralgram_compression_reduction_pct_count" in metrics_text


def test_unknown_source_type_is_422(client: TestClient) -> None:
    response = client.post(
        "/memory/ingest",
        json={
            "source_id": "s",
            "payload": {"messages": []},
            "source_type": "carrier-pigeon",
        },
        headers={"x-api-key": KEY_A},
    )
    assert response.status_code == 422
