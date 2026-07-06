"""C2.2 worker pool: N async workers draining the durable queue.

Workers are woken by ingest (`wake()`) with a polling fallback; a
semaphore caps concurrent model-bound calls. Crash recovery is lease
based: a worker that dies mid-job never acks, its lease expires, and the
job becomes claimable again (proven in the crash-recovery test).
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from neuralgram.memory.queue import ClaimedJob, JobQueue
from neuralgram.observability.logging import get_logger

Handler = Callable[[dict[str, Any]], Awaitable[None]]

DEFAULT_WORKERS = 3
DEFAULT_MODEL_CONCURRENCY = 2
DEFAULT_POLL_INTERVAL_SECONDS = 1.0

logger = get_logger(__name__)


class WorkerPool:
    """Runs registered job handlers against the queue until stopped."""

    def __init__(
        self,
        queue: JobQueue,
        handlers: dict[str, Handler],
        workers: int = DEFAULT_WORKERS,
        model_concurrency: int = DEFAULT_MODEL_CONCURRENCY,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        lease_seconds: int = 60,
    ) -> None:
        self._queue = queue
        self._handlers = handlers
        self._workers = workers
        self._model_semaphore = asyncio.Semaphore(model_concurrency)
        self._poll_interval = poll_interval
        self._lease_seconds = lease_seconds
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def wake(self) -> None:
        """Signal idle workers that new work exists (called by ingest)."""
        self._wake.set()

    async def start(self) -> None:
        """Spawn the worker tasks. Expired leases from a previous run are
        recovered naturally: claim() treats them as runnable."""
        self._tasks = [
            asyncio.create_task(self._worker_loop(f"worker-{i}"), name=f"neuralgram-worker-{i}")
            for i in range(self._workers)
        ]

    async def stop(self) -> None:
        """Cancel all worker tasks and wait for them to unwind."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _worker_loop(self, worker_id: str) -> None:
        while True:
            job = await self._queue.claim(worker_id, lease_seconds=self._lease_seconds)
            if job is None:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
                continue
            await self._run_job(worker_id, job)

    async def _run_job(self, worker_id: str, job: ClaimedJob) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            logger.error("worker.unknown_kind", worker=worker_id, job_id=job.id, kind=job.kind)
            await self._queue.fail(job.id)
            return
        try:
            async with self._model_semaphore:
                await handler(job.payload)
        except asyncio.CancelledError:
            # Simulated/real worker death: no ack, lease will expire -> job resumes.
            raise
        except Exception:
            logger.exception("worker.job_failed", worker=worker_id, job_id=job.id, kind=job.kind)
            await self._finish(self._queue.fail(job.id))
        else:
            await self._finish(self._queue.ack(job.id))

    @staticmethod
    async def _finish(bookkeeping: Awaitable[Any]) -> None:
        """Run ack/fail to completion even if the worker is cancelled mid-await,
        so a graceful stop never strands a finished job in 'leased'."""
        task = asyncio.ensure_future(bookkeeping)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
