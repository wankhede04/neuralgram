"""Integration: durable queue semantics on real Postgres (M2-1 acceptance)."""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from neuralgram.memory.queue import JobQueue
from neuralgram.storage.models import Job

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
async def queue(async_url: str) -> AsyncIterator[JobQueue]:
    engine = create_async_engine(async_url)
    try:
        yield JobQueue(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


@pytest.fixture
async def job_count(async_url: str) -> AsyncIterator[object]:
    engine = create_async_engine(async_url)

    async def _count(dedupe_key: str) -> int:
        async with engine.connect() as connection:
            result = await connection.execute(
                select(func.count()).select_from(Job).where(Job.dedupe_key == dedupe_key)
            )
            return int(result.scalar_one())

    try:
        yield _count
    finally:
        await engine.dispose()


async def test_dedupe_prevents_duplicate_jobs(queue: JobQueue, job_count: object) -> None:
    first = await queue.enqueue("extract_chunk", {"chunk_id": "c1"}, "extract:c1")
    second = await queue.enqueue("extract_chunk", {"chunk_id": "c1"}, "extract:c1")
    assert first is not None
    assert second is None
    assert await job_count("extract:c1") == 1  # type: ignore[operator]
    await queue.ack(first)  # drain so later tests see a clean queue


async def test_claim_leases_and_blocks_other_workers(queue: JobQueue) -> None:
    target = await queue.enqueue("extract_chunk", {"chunk_id": "c2"}, "extract:c2")
    assert target is not None
    claimed = await queue.claim("worker-1", lease_seconds=60)
    assert claimed is not None and claimed.id == target

    stolen = await queue.claim("worker-2", lease_seconds=60)
    assert stolen is None or stolen.id != claimed.id
    await queue.ack(claimed.id)
    if stolen:
        await queue.ack(stolen.id)


async def test_lease_expiry_returns_job_to_queue(queue: JobQueue) -> None:
    await queue.enqueue("extract_chunk", {"chunk_id": "c3"}, "extract:c3")
    claimed = await queue.claim("worker-1", lease_seconds=0)
    assert claimed is not None

    await asyncio.sleep(0.05)
    recovered = await queue.claim("worker-2", lease_seconds=60)
    assert recovered is not None
    assert recovered.id == claimed.id, "expired lease must make the job claimable again"
    await queue.ack(recovered.id)


async def test_run_after_defers_claim(queue: JobQueue) -> None:
    future = datetime.now(tz=UTC) + timedelta(hours=1)
    await queue.enqueue("digest_daily", {"day": "2026-07-06"}, "digest:2026-07-06", future)
    claimed = await queue.claim("worker-1")
    assert claimed is None or claimed.kind != "digest_daily"
    if claimed:
        await queue.ack(claimed.id)


async def test_retries_exhaust_to_failed(queue: JobQueue) -> None:
    await queue.enqueue("extract_chunk", {"chunk_id": "c4"}, "extract:c4")
    claimed = await queue.claim("worker-1")
    assert claimed is not None and claimed.retry_count == 0

    assert await queue.fail(claimed.id) == "queued"  # retry 1, backoff applied
    assert await queue.fail(claimed.id) == "queued"  # retry 2
    assert await queue.fail(claimed.id) == "failed"  # retry 3 == max -> failed


async def test_concurrent_claims_get_distinct_jobs(queue: JobQueue) -> None:
    await queue.enqueue("extract_chunk", {"chunk_id": "c5"}, "extract:c5")
    await queue.enqueue("extract_chunk", {"chunk_id": "c6"}, "extract:c6")

    results = await asyncio.gather(
        queue.claim("worker-1"), queue.claim("worker-2"), queue.claim("worker-3")
    )
    claimed = [r for r in results if r is not None]
    assert len({job.id for job in claimed}) == len(claimed), "no job claimed twice"
    for job in claimed:
        await queue.ack(job.id)
