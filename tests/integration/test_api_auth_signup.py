"""Integration: self-serve signup/login end-to-end against real Postgres."""

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
        )
        with TestClient(create_app(settings)) as test_client:
            yield test_client


def test_signup_returns_usable_key(client: TestClient) -> None:
    response = client.post(
        "/auth/signup", json={"email": "alice@example.com", "password": "hunter2pass"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "writer"
    assert body["tenant_id"].startswith("user-")

    search = client.get(
        "/memory/search", params={"q": "x"}, headers={"x-api-key": body["api_key"]}
    )
    assert search.status_code == 200, search.text


def test_duplicate_signup_email_is_409(client: TestClient) -> None:
    client.post("/auth/signup", json={"email": "bob@example.com", "password": "pw12345678"})
    response = client.post(
        "/auth/signup", json={"email": "bob@example.com", "password": "different-pw"}
    )
    assert response.status_code == 409


def test_login_wrong_password_is_401(client: TestClient) -> None:
    client.post("/auth/signup", json={"email": "carol@example.com", "password": "correct-pw"})
    response = client.post(
        "/auth/login", json={"email": "carol@example.com", "password": "wrong-pw"}
    )
    assert response.status_code == 401


def test_login_unknown_email_is_401(client: TestClient) -> None:
    response = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )
    assert response.status_code == 401


def test_login_issues_new_key_and_invalidates_old(client: TestClient) -> None:
    signup = client.post(
        "/auth/signup", json={"email": "dave@example.com", "password": "original-pw"}
    )
    old_key = signup.json()["api_key"]

    login = client.post(
        "/auth/login", json={"email": "dave@example.com", "password": "original-pw"}
    )
    assert login.status_code == 200, login.text
    new_key = login.json()["api_key"]
    assert new_key != old_key

    old_key_check = client.get(
        "/memory/search", params={"q": "x"}, headers={"x-api-key": old_key}
    )
    assert old_key_check.status_code == 401

    new_key_check = client.get(
        "/memory/search", params={"q": "x"}, headers={"x-api-key": new_key}
    )
    assert new_key_check.status_code == 200, new_key_check.text
