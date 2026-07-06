"""M1-9 E2E spine test — the M1 exit-criteria artifact (BUILD-LOOP §7).

Exercises the full spine through the public API against real Postgres:
ingest real sample data -> lexical search -> fetch, asserting idempotent
re-ingest, provenance on every result, and the token-reduction metric.
"""

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

API_KEY = "e2e-spine-key"  # pragma: allowlist secret
TENANT = "tenant-e2e"


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
            api_keys={API_KEY: TENANT},
        )
        with TestClient(create_app(settings)) as test_client:
            yield test_client


def test_full_spine(client: TestClient) -> None:
    headers = {"x-api-key": API_KEY}
    payload = json.loads(FIXTURE.read_text())

    # 1. Ingest a real sample payload.
    first = client.post(
        "/memory/ingest",
        json={"source_id": "C042MEMORY", "payload": payload},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["chunks_inserted"] > 0

    # 2. Re-ingest is idempotent: zero new chunks.
    second = client.post(
        "/memory/ingest",
        json={"source_id": "C042MEMORY", "payload": payload},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["chunks_inserted"] == 0
    assert second.json()["chunks_skipped"] > 0

    # 3. Search returns the chunk with full provenance.
    hits = client.get("/memory/search", params={"q": "migration checklist"}, headers=headers).json()
    assert hits, "search must find the ingested sample"
    top = hits[0]
    provenance = top["provenance"]
    assert provenance["source_type"] == "slack"
    assert provenance["source_id"] == "C042MEMORY"
    assert provenance["author"] == "U01ALICE"
    assert provenance["url"].startswith("https://example.slack.com")

    # 4. Fetch by id returns the same provenance trail.
    fetched = client.get(f"/memory/chunks/{top['chunk_id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["provenance"]["external_id"] == provenance["external_id"]

    # 5. Token-reduction metric was recorded for the real ingest.
    metrics_text = client.get("/metrics").text
    assert 'neuralgram_compression_tokens_in_total{rule="builtin:' in metrics_text
    assert "neuralgram_compression_reduction_pct_count" in metrics_text
