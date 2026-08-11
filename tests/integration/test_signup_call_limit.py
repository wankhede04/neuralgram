"""Integration: self-serve signup tenants are capped at 3 lifetime calls
per category (completions vs embeddings); static keys and the demo
tenant are unaffected (M7)."""

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
from neuralgram.router.metering import SignupCallLimitExceededError, UsageMeter
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
                hashed_password="not-a-real-hash",
                tenant_id=tenant_id,
                hashed_key=uuid.uuid4().hex,
                role="writer",
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return tenant_id


async def _seed_events(meter: UsageMeter, tenant_id: str, hint: str | None, count: int) -> None:
    for _ in range(count):
        await meter.record(tenant_id, "anthropic", "claude-haiku-4-5-20251001", hint, 10, 10)


async def test_signup_tenant_blocked_after_3_completion_calls(meter: UsageMeter) -> None:
    tenant_id = await _seed_signup_tenant(meter)
    await _seed_events(meter, tenant_id, "summarize", 3)
    with pytest.raises(SignupCallLimitExceededError):
        await meter.check_signup_call_limit(tenant_id, "summarize")


async def test_signup_tenant_completion_cap_independent_of_embed_cap(meter: UsageMeter) -> None:
    tenant_id = await _seed_signup_tenant(meter)
    await _seed_events(meter, tenant_id, "summarize", 3)
    # 3 completion calls used up, but zero embed calls -- embed must still pass.
    await meter.check_signup_call_limit(tenant_id, "embed")


async def test_signup_tenant_blocked_after_3_embed_calls(meter: UsageMeter) -> None:
    tenant_id = await _seed_signup_tenant(meter)
    await _seed_events(meter, tenant_id, "embed", 3)
    with pytest.raises(SignupCallLimitExceededError):
        await meter.check_signup_call_limit(tenant_id, "embed")


async def test_signup_tenant_under_cap_passes(meter: UsageMeter) -> None:
    tenant_id = await _seed_signup_tenant(meter)
    await _seed_events(meter, tenant_id, "fast", 2)
    await meter.check_signup_call_limit(tenant_id, "fast")


async def test_static_tenant_unaffected_even_after_many_calls(meter: UsageMeter) -> None:
    tenant_id = f"{STATIC_TENANT}-{uuid.uuid4().hex}"
    await _seed_events(meter, tenant_id, "summarize", 10)
    await meter.check_signup_call_limit(tenant_id, "summarize")


async def test_null_hint_completion_call_counts_toward_completion_cap(
    meter: UsageMeter,
) -> None:
    tenant_id = await _seed_signup_tenant(meter)
    # A bare-model completion call records hint=None; it must still count
    # as a completion (non-embed) call, not be silently excluded by NULL
    # three-valued logic in the SQL filter.
    await meter.record(tenant_id, "anthropic", "some-model", None, 10, 10)
    await _seed_events(meter, tenant_id, "summarize", 2)
    with pytest.raises(SignupCallLimitExceededError):
        await meter.check_signup_call_limit(tenant_id, "summarize")


def test_signup_tenant_search_gets_real_429_over_http(
    async_url: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The one live user-visible path: a real HTTP /memory/search request past
    the embed cap must return a 429 with a readable, non-leaking detail body."""
    settings = Settings(
        _env_file=None,
        database_url=async_url,
        vault_path=str(tmp_path_factory.mktemp("vault")),
    )
    with TestClient(create_app(settings)) as client:
        signup = client.post(
            "/auth/signup",
            json={"email": f"{uuid.uuid4().hex}@example.com", "password": "hunter2pass"},
        )
        assert signup.status_code == 201, signup.text
        body = signup.json()
        api_key = body["api_key"]
        tenant_id = body["tenant_id"]

        engine = create_async_engine(async_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        meter = UsageMeter(session_factory=factory, spend_caps_usd={})

        import asyncio

        asyncio.run(_seed_events(meter, tenant_id, "embed", 3))

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
