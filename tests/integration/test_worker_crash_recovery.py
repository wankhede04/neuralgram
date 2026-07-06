"""Integration: worker killed mid-job -> job resumes via lease expiry (M2-2 acceptance)."""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from neuralgram.memory.queue import JobQueue
from neuralgram.memory.workers import WorkerPool
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


async def test_worker_killed_mid_job_job_resumes(async_url: str, queue: JobQueue) -> None:
    """Kill a worker while its handler is running; the job must be re-claimed
    after lease expiry and completed by a second pool — no lost admits."""
    started = asyncio.Event()
    completions: list[dict[str, Any]] = []

    async def hanging_handler(payload: dict[str, Any]) -> None:
        started.set()
        await asyncio.sleep(3600)  # never finishes; the pool gets killed mid-job

    async def completing_handler(payload: dict[str, Any]) -> None:
        completions.append(payload)

    job_id = await queue.enqueue("extract_chunk", {"chunk_id": "crash-1"}, "extract:crash-1")
    assert job_id is not None

    # Pool A claims the job (1s lease) and dies mid-handler without acking.
    pool_a = WorkerPool(
        queue, {"extract_chunk": hanging_handler}, workers=1, poll_interval=0.05, lease_seconds=1
    )
    await pool_a.start()
    await asyncio.wait_for(started.wait(), timeout=10.0)
    await pool_a.stop()  # kill mid-job: no ack, lease still held

    # Pool B must pick the job up once the lease expires and complete it.
    pool_b = WorkerPool(
        queue,
        {"extract_chunk": completing_handler},
        workers=1,
        poll_interval=0.05,
        lease_seconds=60,
    )
    await pool_b.start()
    for _ in range(400):  # up to ~20s for the 1s lease to expire + reclaim
        if completions:
            break
        await asyncio.sleep(0.05)
    await pool_b.stop()

    assert completions == [{"chunk_id": "crash-1"}], "job must resume after worker death"

    engine = create_async_engine(async_url)
    try:
        async with engine.connect() as connection:
            status = (
                await connection.execute(select(Job.status).where(Job.id == job_id))
            ).scalar_one()
    finally:
        await engine.dispose()
    assert status == "done", "recovered job must be acked done"
