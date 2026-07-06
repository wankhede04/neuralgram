"""Integration: GDPR erasure leaves no residue anywhere (M5-3 acceptance).

Seeds the full pipeline output for two tenants through the real API
(ingest -> extraction -> embeddings -> entities -> trees via workers),
erases one, and asserts zero residue — including embeddings and vault
files — while the other tenant is untouched.
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from neuralgram.api.app import create_app
from neuralgram.common.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "slack_export_sample.json"

ERASE_KEY = "erase-admin-key"  # pragma: allowlist secret
KEEP_KEY = "keep-admin-key"  # pragma: allowlist secret
ERASE_TENANT = "tenant-erase"
KEEP_TENANT = "tenant-keep"

TENANT_TABLES = ("chunks", "scores", "entities", "chunk_entities", "summaries")


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, str, Path]]:
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

        vault = tmp_path_factory.mktemp("vault")
        settings = Settings(
            _env_file=None,
            database_url=url,
            vault_path=str(vault),
            api_keys={ERASE_KEY: ERASE_TENANT, KEEP_KEY: KEEP_TENANT},
            api_key_roles={ERASE_KEY: "admin", KEEP_KEY: "admin"},
        )
        with TestClient(create_app(settings)) as client:
            yield client, url, vault


def _counts(async_url: str, tenant: str) -> dict[str, int]:
    # psycopg2 is unavailable; use asyncpg via a throwaway async engine.
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def _query() -> dict[str, int]:
        engine = create_async_engine(async_url)
        out: dict[str, int] = {}
        try:
            async with engine.connect() as conn:
                for table in TENANT_TABLES:
                    result = await conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
                        {"t": tenant},
                    )
                    out[table] = int(result.scalar_one())
                embeddings = await conn.execute(
                    text(
                        "SELECT count(*) FROM scores WHERE tenant_id = :t AND embedding IS NOT NULL"
                    ),
                    {"t": tenant},
                )
                out["embeddings"] = int(embeddings.scalar_one())
                jobs = await conn.execute(
                    text("SELECT count(*) FROM jobs WHERE payload->>'tenant_id' = :t"),
                    {"t": tenant},
                )
                out["tenant_jobs"] = int(jobs.scalar_one())
        finally:
            await engine.dispose()
        return out

    return asyncio.run(_query())


def _ingest_and_wait(client: TestClient, key: str, async_url: str, tenant: str) -> None:
    response = client.post(
        "/memory/ingest",
        json={"source_id": "C042MEMORY", "payload": json.loads(FIXTURE.read_text())},
        headers={"x-api-key": key},
    )
    assert response.status_code == 200, response.text
    deadline = time.time() + 30
    while time.time() < deadline:
        counts = _counts(async_url, tenant)
        if counts["embeddings"] > 0 and counts["entities"] > 0:
            return
        time.sleep(0.5)
    raise AssertionError(f"extraction pipeline did not enrich {tenant} in time")


def test_erasure_leaves_no_residue_and_spares_other_tenants(
    env: tuple[TestClient, str, Path],
) -> None:
    client, async_url, vault = env
    _ingest_and_wait(client, ERASE_KEY, async_url, ERASE_TENANT)
    _ingest_and_wait(client, KEEP_KEY, async_url, KEEP_TENANT)

    before = _counts(async_url, ERASE_TENANT)
    assert before["chunks"] > 0 and before["embeddings"] > 0 and before["entities"] > 0
    assert (vault / ERASE_TENANT).exists()

    response = client.post("/admin/erase", headers={"x-api-key": ERASE_KEY})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["chunks"] == before["chunks"]
    assert report["vault_files"] > 0

    after = _counts(async_url, ERASE_TENANT)
    assert all(count == 0 for count in after.values()), f"residue found: {after}"
    assert not (vault / ERASE_TENANT).exists(), "vault directory must be gone"

    keep = _counts(async_url, KEEP_TENANT)
    assert keep["chunks"] > 0 and keep["embeddings"] > 0, "other tenants must be untouched"
    assert (vault / KEEP_TENANT).exists()


def test_non_admin_cannot_erase(env: tuple[TestClient, str, Path]) -> None:
    client, _, _ = env
    # Re-use the reader-less setup: an unknown key gets 401; a known non-admin is
    # covered in test_rbac_audit; here assert the endpoint demands auth at all.
    assert client.post("/admin/erase").status_code == 401
