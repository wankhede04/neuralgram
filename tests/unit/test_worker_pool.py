"""Unit tests for WorkerPool semantics against an in-memory queue (M2-2)."""

import asyncio
from typing import Any

from neuralgram.memory.queue import ClaimedJob
from neuralgram.memory.workers import DEFAULT_CLAIM_ERROR_BACKOFF_SECONDS, WorkerPool


class InMemoryQueue:
    """Queue stand-in: hands out preloaded jobs, records acks/fails."""

    def __init__(self, jobs: list[ClaimedJob]) -> None:
        self._jobs = list(jobs)
        self.acked: list[str] = []
        self.failed: list[str] = []

    async def claim(self, worker_id: str, lease_seconds: int = 60) -> ClaimedJob | None:
        return self._jobs.pop(0) if self._jobs else None

    async def ack(self, job_id: str) -> None:
        self.acked.append(job_id)

    async def fail(self, job_id: str) -> str:
        self.failed.append(job_id)
        return "queued"


def _jobs(n: int, kind: str = "extract_chunk") -> list[ClaimedJob]:
    return [ClaimedJob(id=f"job-{i}", kind=kind, payload={"i": i}, retry_count=0) for i in range(n)]


async def _drain(pool: WorkerPool, queue: InMemoryQueue, expected: int) -> None:
    await pool.start()
    for _ in range(200):
        if len(queue.acked) + len(queue.failed) >= expected:
            break
        await asyncio.sleep(0.01)
    await pool.stop()


async def test_semaphore_caps_concurrent_model_calls() -> None:
    peak = 0
    active = 0

    async def handler(payload: dict[str, Any]) -> None:
        nonlocal peak, active
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1

    queue = InMemoryQueue(_jobs(6))
    pool = WorkerPool(
        queue,  # type: ignore[arg-type]
        {"extract_chunk": handler},
        workers=3,
        model_concurrency=1,
        poll_interval=0.01,
    )
    await _drain(pool, queue, expected=6)

    assert len(queue.acked) == 6
    assert peak == 1, f"semaphore must cap concurrency at 1, saw {peak}"


async def test_failing_handler_marks_job_failed_not_acked() -> None:
    async def handler(payload: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    queue = InMemoryQueue(_jobs(2))
    pool = WorkerPool(
        queue,  # type: ignore[arg-type]
        {"extract_chunk": handler},
        workers=1,
        poll_interval=0.01,
    )
    await _drain(pool, queue, expected=2)
    assert queue.acked == []
    assert len(queue.failed) == 2


async def test_unknown_kind_is_failed() -> None:
    queue = InMemoryQueue(_jobs(1, kind="mystery"))
    pool = WorkerPool(queue, {}, workers=1, poll_interval=0.01)  # type: ignore[arg-type]
    await _drain(pool, queue, expected=1)
    assert queue.failed == ["job-0"]


async def test_transient_claim_error_does_not_permanently_kill_the_worker(
    monkeypatch: Any,
) -> None:
    """A claim() failure (e.g. schema not ready yet, or a DB blip) must be
    logged and retried, not silently end the worker task forever -- there
    is no supervisor to restart it."""
    import neuralgram.memory.workers as workers_module

    monkeypatch.setattr(workers_module, "DEFAULT_CLAIM_ERROR_BACKOFF_SECONDS", 0.01)

    class FlakyQueue(InMemoryQueue):
        def __init__(self, jobs: list[ClaimedJob]) -> None:
            super().__init__(jobs)
            self._claim_attempts = 0

        async def claim(self, worker_id: str, lease_seconds: int = 60) -> ClaimedJob | None:
            self._claim_attempts += 1
            if self._claim_attempts == 1:
                raise RuntimeError('relation "jobs" does not exist')
            return await super().claim(worker_id, lease_seconds)

    queue = FlakyQueue(_jobs(1))
    pool = WorkerPool(
        queue,  # type: ignore[arg-type]
        {"extract_chunk": lambda payload: asyncio.sleep(0)},
        workers=1,
        poll_interval=0.01,
    )
    await _drain(pool, queue, expected=1)

    assert queue.acked == ["job-0"], "the job must still be processed after the first claim() error"
    assert DEFAULT_CLAIM_ERROR_BACKOFF_SECONDS == 2.0, "module default is unchanged for real use"


async def test_wake_triggers_idle_workers_before_poll() -> None:
    done = asyncio.Event()

    async def handler(payload: dict[str, Any]) -> None:
        done.set()

    queue = InMemoryQueue([])
    pool = WorkerPool(
        queue,  # type: ignore[arg-type]
        {"extract_chunk": handler},
        workers=1,
        poll_interval=60.0,  # polling alone would take a minute
    )
    await pool.start()
    await asyncio.sleep(0.05)  # let the worker go idle
    queue._jobs = _jobs(1)
    pool.wake()
    await asyncio.wait_for(done.wait(), timeout=2.0)
    await pool.stop()
    assert queue.acked == ["job-0"]
