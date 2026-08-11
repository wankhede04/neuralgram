"""Integration: self-serve signup tenants are capped at 4 lifetime requests
per action -- ingest calls and AI-backed (semantic/hybrid) search calls are
counted and capped independently; keyword search and summaries need no AI
call and are never capped; static keys and the demo tenant are unaffected
(M7)."""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from neuralgram.api.app import create_app
from neuralgram.common.config import Settings
from neuralgram.router.metering import SEARCH_AI_HINT, SignupCallLimitExceededError, UsageMeter
from neuralgram.storage.models import User

REPO_ROOT = Path(__file__).resolve().parents[2]

SIGNUP_TENANT = "test-signup-tenant"
STATIC_TENANT = "test-static-tenant"


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


@pytest.fixture()
async def meter(async_url: str) -> UsageMeter:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return UsageMeter(session_factory=factory, spend_caps_usd={})


async def _seed_signup_tenant(meter: UsageMeter) -> str:
    """Seed a fresh signup user row for a unique tenant_id and return it.

    A fresh tenant per test keeps tests independent even though they
    share the module-scoped database (User.tenant_id is unique, and
    usage_events accumulate across tests within the same tenant_id).
    """
    tenant_id = f"{SIGNUP_TENANT}-{uuid.uuid4().hex}"
    async with meter._session_factory() as session:
        await session.execute(
            insert(User).values(
                id=uuid.uuid4().hex,
                email=f"{uuid.uuid4().hex}@example.com",
                hashed_password="not-a-real-hash",  # pragma: allowlist secret
                tenant_id=tenant_id,
                hashed_key=uuid.uuid4().hex,
                role="writer",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return tenant_id


async def _make_ingest_requests(meter: UsageMeter, tenant_id: str, count: int) -> None:
    """Call the real check-and-record path `count` times (each a successful ingest)."""
    for _ in range(count):
        await meter.check_and_record_ingest_request(tenant_id)


async def _seed_search_ai_calls(meter: UsageMeter, tenant_id: str, count: int) -> None:
    for _ in range(count):
        await meter.record(tenant_id, "jina", "jina-embeddings-v3", SEARCH_AI_HINT, 10, 0)


async def test_signup_tenant_blocked_after_4_ingest_calls(meter: UsageMeter) -> None:
    tenant_id = await _seed_signup_tenant(meter)
    await _make_ingest_requests(meter, tenant_id, 4)
    with pytest.raises(SignupCallLimitExceededError):
        await meter.check_and_record_ingest_request(tenant_id)


async def test_ingest_cap_independent_of_search_ai_cap(meter: UsageMeter) -> None:
    tenant_id = await _seed_signup_tenant(meter)
    await _make_ingest_requests(meter, tenant_id, 4)
    # 4 ingest calls used up, but zero search-AI calls -- search must still pass.
    await meter.check_search_ai_request_limit(tenant_id)


async def test_signup_tenant_blocked_after_4_search_ai_calls(meter: UsageMeter) -> None:
    tenant_id = await _seed_signup_tenant(meter)
    await _seed_search_ai_calls(meter, tenant_id, 4)
    with pytest.raises(SignupCallLimitExceededError):
        await meter.check_search_ai_request_limit(tenant_id)


async def test_signup_tenant_under_cap_passes(meter: UsageMeter) -> None:
    tenant_id = await _seed_signup_tenant(meter)
    await _make_ingest_requests(meter, tenant_id, 3)
    await _seed_search_ai_calls(meter, tenant_id, 3)
    # The 4th of each is still under the limit -- must not raise.
    await meter.check_and_record_ingest_request(tenant_id)
    await meter.check_search_ai_request_limit(tenant_id)


async def test_static_tenant_unaffected_even_after_many_calls(meter: UsageMeter) -> None:
    tenant_id = f"{STATIC_TENANT}-{uuid.uuid4().hex}"
    await _make_ingest_requests(meter, tenant_id, 10)
    await _seed_search_ai_calls(meter, tenant_id, 10)
    await meter.check_and_record_ingest_request(tenant_id)
    await meter.check_search_ai_request_limit(tenant_id)


def test_signup_tenant_search_gets_real_429_over_http(
    async_url: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The one live user-visible path: a real HTTP /memory/search request past
    the search-AI cap must return a 429 with a readable, non-leaking detail body."""
    settings = Settings(
        _env_file=None,
        database_url=async_url,
        vault_path=str(tmp_path_factory.mktemp("vault")),
    )
    with TestClient(create_app(settings)) as client:
        signup = client.post(
            "/auth/signup",
            json={
                "email": f"{uuid.uuid4().hex}@example.com",
                "password": "hunter2pass",  # pragma: allowlist secret
            },
        )
        assert signup.status_code == 201, signup.text
        body = signup.json()
        api_key = body["api_key"]
        tenant_id = body["tenant_id"]

        engine = create_async_engine(async_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        meter = UsageMeter(session_factory=factory, spend_caps_usd={})
        asyncio.run(_seed_search_ai_calls(meter, tenant_id, 4))

        response = client.get(
            "/memory/search",
            params={"q": "test", "mode": "semantic"},
            headers={"x-api-key": api_key},
        )

        assert response.status_code == 429, response.text
        detail = response.json()["detail"]
        assert isinstance(detail, str)
        assert detail
        assert tenant_id not in detail


def test_ingest_cap_counts_requests_not_messages_over_http(
    async_url: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A single ingest call with many messages must still only spend one
    slot of the lifetime ingest cap -- 4 calls (any message count each)
    succeed, the 5th is blocked."""
    settings = Settings(
        _env_file=None,
        database_url=async_url,
        vault_path=str(tmp_path_factory.mktemp("vault-ingest-count")),
    )
    with TestClient(create_app(settings)) as client:
        signup = client.post(
            "/auth/signup",
            json={
                "email": f"{uuid.uuid4().hex}@example.com",
                "password": "hunter2pass",  # pragma: allowlist secret
            },
        )
        assert signup.status_code == 201, signup.text
        api_key = signup.json()["api_key"]

        def ingest(n: int) -> int:
            payload = {
                "messages": [{"user": "a", "text": f"m{i}", "ts": f"{i}.0"} for i in range(n)]
            }
            resp = client.post(
                "/memory/ingest",
                json={"source_id": "count-src", "payload": payload},
                headers={"x-api-key": api_key},
            )
            return resp.status_code

        assert ingest(3) == 200
        assert ingest(1) == 200
        assert ingest(5) == 200
        assert ingest(2) == 200
        assert ingest(1) == 429
