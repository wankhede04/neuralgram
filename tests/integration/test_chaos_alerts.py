"""Chaos test (M5-4 acceptance): induce failures, alerts fire on real metrics."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from neuralgram.memory.queue import JobQueue
from neuralgram.observability import metrics
from neuralgram.observability.alerts import evaluate_alerts
from neuralgram.observability.queue_monitor import QueueDepthMonitor

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
async def queue(async_url: str) -> AsyncIterator[tuple[JobQueue, QueueDepthMonitor]]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield JobQueue(factory, max_retries=1), QueueDepthMonitor(factory)
    finally:
        await engine.dispose()


async def test_induced_job_failures_fire_the_alert(
    queue: tuple[JobQueue, QueueDepthMonitor],
) -> None:
    """Chaos: a broken handler exhausts retries -> failed jobs -> alert fires."""
    job_queue, monitor = queue

    def failed_total() -> float:
        total = 0.0
        for metric in metrics.registry.collect():
            for sample in metric.samples:
                if sample.name == "neuralgram_jobs_failed_total":
                    total += sample.value
        return total

    before = failed_total()
    await job_queue.enqueue("extract_chunk", {"chunk_id": "chaos-1"}, "chaos:extract-1")
    job = await job_queue.claim("chaos-worker")
    assert job is not None
    status = await job_queue.fail(job.id)  # max_retries=1: first failure exhausts
    assert status == "failed"

    monitor_counts = await monitor.sample()
    assert monitor_counts["failed"] >= 1, "gauge must reflect the failed job"

    assert failed_total() == before + 1, "chaos failure must be counted"
    fired = evaluate_alerts(metrics.registry)
    assert "NeuralgramJobFailures" in fired, f"alert must fire; got {fired}"


async def test_queue_backlog_alert_threshold(queue: tuple[JobQueue, QueueDepthMonitor]) -> None:
    """The backlog rule keys off the gauge the monitor maintains."""
    _, monitor = queue
    await monitor.sample()
    assert "NeuralgramQueueBacklogHigh" not in evaluate_alerts(metrics.registry)

    metrics.queue_depth.labels("queued").set(101)  # simulate sustained backlog
    assert "NeuralgramQueueBacklogHigh" in evaluate_alerts(metrics.registry)

    await monitor.sample()  # real sample restores the true (low) depth
    assert "NeuralgramQueueBacklogHigh" not in evaluate_alerts(metrics.registry)
