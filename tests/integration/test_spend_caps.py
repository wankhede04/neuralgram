"""Integration: usage attribution + hard spend caps (M4-3 acceptance)."""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from neuralgram.common.config import Settings
from neuralgram.router.gateway import Message, build_gateway
from neuralgram.router.metering import (
    SignupCallLimitExceededError,
    SpendCapExceededError,
    UsageMeter,
)
from neuralgram.storage.models import UsageEvent, User

REPO_ROOT = Path(__file__).resolve().parents[2]


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


@pytest.fixture
async def engine(async_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(async_url)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_usage_is_recorded_and_attributed_per_tenant(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    meter = UsageMeter(factory, spend_caps_usd={})
    gateway = build_gateway(Settings(_env_file=None), meter)

    await gateway.complete(
        [Message(role="user", content="hello world example")], "hint:fast", tenant_id="tenant-a"
    )
    await gateway.embed(["some text to embed"], tenant_id="tenant-b")

    async with factory() as session:
        events = (await session.execute(select(UsageEvent))).scalars().all()
    by_tenant = {e.tenant_id: e for e in events}
    assert set(by_tenant) >= {"tenant-a", "tenant-b"}
    assert by_tenant["tenant-a"].hint == "fast"
    assert by_tenant["tenant-a"].tokens_in > 0
    assert by_tenant["tenant-a"].cost_usd > 0
    assert by_tenant["tenant-b"].hint == "embed"
    assert await meter.spent_usd("tenant-a") > Decimal("0")


async def test_cap_trips_and_blocks_further_spend(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    meter = UsageMeter(factory, spend_caps_usd={"tenant-capped": 0.000001})
    gateway = build_gateway(Settings(_env_file=None), meter)

    # First call is under the cap (nothing spent yet) and records usage.
    await gateway.complete(
        [Message(role="user", content="x " * 200)], "hint:reasoning", tenant_id="tenant-capped"
    )
    assert await meter.spent_usd("tenant-capped") > Decimal("0.000001")

    # Now the cap is exceeded: every further call must be blocked pre-flight.
    with pytest.raises(SpendCapExceededError, match="spend cap"):
        await gateway.complete(
            [Message(role="user", content="more")], "hint:fast", tenant_id="tenant-capped"
        )
    with pytest.raises(SpendCapExceededError):
        await gateway.embed(["more"], tenant_id="tenant-capped")

    # Other tenants are unaffected.
    await gateway.complete(
        [Message(role="user", content="fine")], "hint:fast", tenant_id="tenant-free"
    )


async def test_uncapped_and_unmetered_calls_pass(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    meter = UsageMeter(factory, spend_caps_usd={"someone-else": 5.0})
    gateway = build_gateway(Settings(_env_file=None), meter)

    await gateway.complete([Message(role="user", content="no tenant")], "hint:fast")

    async with factory() as session:
        events = (
            (await session.execute(select(UsageEvent).where(UsageEvent.tenant_id == "none")))
            .scalars()
            .all()
        )
    assert events == [], "calls without tenant context are not attributed"


async def test_concurrent_calls_never_exceed_the_signup_lifetime_cap(
    async_url: str,
) -> None:
    """15 concurrent calls against a limit of 3 must never let more than 3 through.

    Regression for a check-then-act race: without `UsageMeter.tenant_lock`
    serializing check + provider-call + record per tenant, concurrent
    requests can all pass the pre-flight count check before any of them is
    recorded, letting a deliberate burst blow past the cap entirely.

    Uses a wider pool than the other tests here (matching `build_engine`'s
    production sizing) since the advisory lock holds a connection per
    in-flight concurrent call on this tenant.
    """
    engine = create_async_engine(async_url, pool_size=20, max_overflow=30)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            User(
                id="race-user",
                email="race@example.com",
                hashed_password="x",
                tenant_id="race-tenant",
                hashed_key="race-hashed-key",
                role="writer",
            )
        )
        await session.commit()

    meter = UsageMeter(factory, spend_caps_usd={}, signup_call_limit=3)
    gateway = build_gateway(Settings(_env_file=None), meter)

    async def one_call(i: int) -> str:
        try:
            await gateway.complete(
                [Message(role="user", content=f"call {i}")], "hint:fast", tenant_id="race-tenant"
            )
        except SignupCallLimitExceededError:
            return "blocked"
        return "ok"

    try:
        results = await asyncio.gather(*(one_call(i) for i in range(15)))
    finally:
        await engine.dispose()
    assert results.count("ok") == 3, (
        f"expected exactly 3 calls to succeed, got {results.count('ok')}: {results}"
    )
