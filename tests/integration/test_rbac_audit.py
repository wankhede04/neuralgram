"""Integration: RBAC denial + audit trail (M5-2 acceptance)."""

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
from neuralgram.api.deps import key_fingerprint
from neuralgram.common.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "slack_export_sample.json"

READER_KEY = "rbac-reader-key"  # pragma: allowlist secret
WRITER_KEY = "rbac-writer-key"  # pragma: allowlist secret
ADMIN_KEY = "rbac-admin-key"  # pragma: allowlist secret
OTHER_ADMIN_KEY = "rbac-other-admin-key"  # pragma: allowlist secret
TENANT = "tenant-rbac"


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
            api_keys={
                READER_KEY: TENANT,
                WRITER_KEY: TENANT,
                ADMIN_KEY: TENANT,
                OTHER_ADMIN_KEY: "tenant-other",
            },
            api_key_roles={READER_KEY: "reader", ADMIN_KEY: "admin", OTHER_ADMIN_KEY: "admin"},
        )
        with TestClient(create_app(settings)) as test_client:
            yield test_client


def _audit(client: TestClient, key: str) -> list[dict[str, object]]:
    response = client.get("/admin/audit", headers={"x-api-key": key})
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_reader_can_search_but_not_ingest_and_denial_is_audited(client: TestClient) -> None:
    search = client.get(
        "/memory/search", params={"q": "anything"}, headers={"x-api-key": READER_KEY}
    )
    assert search.status_code == 200

    denied = client.post(
        "/memory/ingest",
        json={"source_id": "s", "payload": json.loads(FIXTURE.read_text())},
        headers={"x-api-key": READER_KEY},
    )
    assert denied.status_code == 403

    trail = _audit(client, ADMIN_KEY)
    denials = [e for e in trail if e["status"] == 403 and e["resource"] == "/memory/ingest"]
    assert denials, "the 403 denial must appear in the audit trail"
    assert denials[0]["actor"] == key_fingerprint(READER_KEY)
    assert READER_KEY not in json.dumps(trail), "raw keys never appear in the trail"


def test_writer_can_ingest_and_access_is_audited(client: TestClient) -> None:
    ok = client.post(
        "/memory/ingest",
        json={"source_id": "C042MEMORY", "payload": json.loads(FIXTURE.read_text())},
        headers={"x-api-key": WRITER_KEY},
    )
    assert ok.status_code == 200

    trail = _audit(client, ADMIN_KEY)
    writes = [
        e
        for e in trail
        if e["status"] == 200
        and e["resource"] == "/memory/ingest"
        and e["actor"] == key_fingerprint(WRITER_KEY)
    ]
    assert writes, "successful writes are audited with the writer's fingerprint"


def test_invalid_key_denial_is_audited(client: TestClient) -> None:
    denied = client.get(
        "/memory/search", params={"q": "x"}, headers={"x-api-key": "not-a-real-key"}
    )
    assert denied.status_code == 401

    # 401s carry no tenant; they are recorded under 'unknown' (system-visible only),
    # so the tenant-scoped admin trail must NOT contain them.
    trail = _audit(client, ADMIN_KEY)
    assert all(e["status"] != 401 for e in trail)


def test_non_admin_cannot_query_audit(client: TestClient) -> None:
    for key in (READER_KEY, WRITER_KEY):
        response = client.get("/admin/audit", headers={"x-api-key": key})
        assert response.status_code == 403


def test_admin_sees_only_own_tenant_trail(client: TestClient) -> None:
    client.get("/memory/search", params={"q": "seed"}, headers={"x-api-key": READER_KEY})
    other_trail = _audit(client, OTHER_ADMIN_KEY)
    own_actors = {key_fingerprint(READER_KEY), key_fingerprint(WRITER_KEY)}
    assert all(e["actor"] not in own_actors for e in other_trail), (
        "another tenant's admin must not see this tenant's audit events"
    )
