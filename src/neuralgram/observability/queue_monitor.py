"""Queue-depth monitor (C8, M5-4): keeps the queue_depth gauge current."""

import asyncio
import contextlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neuralgram.observability import metrics
from neuralgram.storage.models import Job

DEFAULT_INTERVAL_SECONDS = 15.0
STATUSES = ("queued", "leased", "failed", "done")


class QueueDepthMonitor:
    """Periodically samples jobs-by-status into the queue_depth gauge."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def sample(self) -> dict[str, int]:
        """Take one sample; updates the gauge and returns counts by status."""
        async with self._session_factory() as session:
            rows = await session.execute(select(Job.status, func.count()).group_by(Job.status))
            counts = dict.fromkeys(STATUSES, 0)
            for status, count in rows:
                counts[status] = int(count)
        for status, count in counts.items():
            metrics.queue_depth.labels(status).set(count)
        return counts

    def start(self) -> None:
        """Start periodic sampling as a background task."""
        self._task = asyncio.create_task(self._run(), name="neuralgram-queue-monitor")

    async def stop(self) -> None:
        """Cancel the sampling loop."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            with contextlib.suppress(Exception):
                await self.sample()
            await asyncio.sleep(self._interval)
