"""Integration: daily digest for a simulated day; idempotent scheduling (M3-3 acceptance)."""

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
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
from neuralgram.memory.digest import DigestBuilder, DigestScheduler
from neuralgram.memory.queue import JobQueue
from neuralgram.router.gateway import build_gateway
from neuralgram.storage.models import Chunk, Summary

REPO_ROOT = Path(__file__).resolve().parents[2]
TENANT = "tenant-digest"
SIMULATED_DAY = datetime(2026, 7, 5, tzinfo=UTC)  # "yesterday" for a 2026-07-06 tick


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


async def _seed_day_chunks(engine: AsyncEngine, count: int) -> list[str]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = []
    async with factory() as session:
        for i in range(count):
            chunk_id = uuid.uuid4().hex
            session.add(
                Chunk(
                    id=chunk_id,
                    tenant_id=TENANT,
                    source_id="C042MEMORY",
                    content_md=f"digest item {i} for the simulated day",
                    token_count=6,
                    provenance={"source_type": "slack"},
                    lifecycle="admitted",
                    content_hash=chunk_id,
                    created_at=SIMULATED_DAY + timedelta(hours=i + 1),
                )
            )
            ids.append(chunk_id)
        await session.commit()
    return ids


async def _global_nodes(engine: AsyncEngine) -> list[Summary]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(Summary).where(
                        Summary.tenant_id == TENANT, Summary.tree_type == "global"
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_digest_builds_one_node_for_simulated_day_and_is_idempotent(
    engine: AsyncEngine,
) -> None:
    ids = await _seed_day_chunks(engine, 3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    builder = DigestBuilder(factory, build_gateway(Settings(_env_file=None)))
    payload = {"tenant_id": TENANT, "day": "2026-07-05"}

    await builder.digest_daily(payload)
    nodes = await _global_nodes(engine)
    assert len(nodes) == 1
    assert nodes[0].scope_id == "2026-07-05"
    assert set(nodes[0].child_ids["chunks"]) == set(ids)

    await builder.digest_daily(payload)  # re-run refreshes, never duplicates
    assert len(await _global_nodes(engine)) == 1

    await builder.digest_daily({"tenant_id": TENANT, "day": "2026-01-01"})  # empty day
    assert len(await _global_nodes(engine)) == 1, "empty days create no node"


async def test_scheduler_tick_is_idempotent_via_dedupe(engine: AsyncEngine) -> None:
    await _seed_day_chunks(engine, 1)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scheduler = DigestScheduler(JobQueue(factory), factory)
    tick_now = datetime(2026, 7, 6, 0, 0, tzinfo=UTC)

    first = await scheduler.tick(tick_now)
    second = await scheduler.tick(tick_now)
    assert first == 1, "one tenant active on the simulated day"
    assert second == 0, "second tick must dedupe to zero new jobs"
