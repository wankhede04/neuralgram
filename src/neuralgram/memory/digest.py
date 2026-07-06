"""C2.4 global tree: one digest node per tenant per day (M3-3).

The scheduler enqueues `digest_daily` at 00:00 UTC for the day just
ended; queue dedupe keys (`digest:{tenant}:{day}`) make scheduling
idempotent. The builder is also idempotent: one node per (tenant, day),
refreshed on re-run.
"""

import asyncio
import contextlib
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neuralgram.compression.engine import compress
from neuralgram.memory.queue import JobQueue
from neuralgram.observability.logging import get_logger
from neuralgram.router.gateway import Message, ModelGateway
from neuralgram.storage.models import Chunk, Summary

DIGEST_BUDGET_TOKENS = 1500

logger = get_logger(__name__)


def next_midnight_utc(now: datetime) -> datetime:
    """Return the next 00:00 UTC strictly after `now`."""
    return datetime.combine(now.date() + timedelta(days=1), time(0, 0), tzinfo=UTC)


class DigestBuilder:
    """Builds the per-day global digest node for a tenant."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], gateway: ModelGateway
    ) -> None:
        self._session_factory = session_factory
        self._gateway = gateway

    async def digest_daily(self, payload: dict[str, Any]) -> None:
        """Handler for `digest_daily`; payload = {"tenant_id", "day": "YYYY-MM-DD"}.

        Summarizes chunks admitted/sealed on `day`; one node per (tenant,
        day), refreshed if it already exists. No node for an empty day.
        """
        tenant_id = payload["tenant_id"]
        day = date.fromisoformat(payload["day"])
        start = datetime.combine(day, time(0, 0), tzinfo=UTC)
        end = start + timedelta(days=1)

        async with self._session_factory() as session:
            chunks = (
                (
                    await session.execute(
                        select(Chunk)
                        .where(
                            Chunk.tenant_id == tenant_id,
                            Chunk.lifecycle.in_(("admitted", "buffered", "sealed")),
                            Chunk.created_at >= start,
                            Chunk.created_at < end,
                        )
                        .order_by(Chunk.created_at)
                    )
                )
                .scalars()
                .all()
            )
            if not chunks:
                logger.info("digest.empty_day", tenant=tenant_id, day=str(day))
                return

            compressed = compress(
                "\n\n---\n\n".join(c.content_md for c in chunks), DIGEST_BUDGET_TOKENS
            )
            reply = await self._gateway.complete(
                [Message(role="user", content=f"Daily digest:\n\n{compressed.text}")],
                "hint:summarize",
                tenant_id=tenant_id,
            )
            child_ids = {"chunks": [c.id for c in chunks]}

            existing = (
                await session.execute(
                    select(Summary).where(
                        Summary.tenant_id == tenant_id,
                        Summary.tree_type == "global",
                        Summary.scope_id == str(day),
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    Summary(
                        id=uuid.uuid4().hex,
                        tenant_id=tenant_id,
                        tree_type="global",
                        scope_id=str(day),
                        level=1,
                        body_md=reply.text,
                        child_ids=child_ids,
                    )
                )
            else:
                existing.body_md = reply.text
                existing.child_ids = child_ids
            await session.commit()
            logger.info("digest.built", tenant=tenant_id, day=str(day), chunks=len(chunks))


class DigestScheduler:
    """Enqueues digest_daily for every active tenant at 00:00 UTC."""

    def __init__(
        self,
        queue: JobQueue,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._queue = queue
        self._session_factory = session_factory
        self._task: asyncio.Task[None] | None = None

    async def tick(self, now: datetime) -> int:
        """Enqueue digests for the day that ended at `now`; returns newly enqueued count.

        Safe to call repeatedly: the queue dedupe key makes duplicates no-ops.
        """
        day = (now - timedelta(days=1)).date()
        start = datetime.combine(day, time(0, 0), tzinfo=UTC)
        end = start + timedelta(days=1)
        async with self._session_factory() as session:
            tenants = (
                (
                    await session.execute(
                        select(Chunk.tenant_id)
                        .where(Chunk.created_at >= start, Chunk.created_at < end)
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
        enqueued = 0
        for tenant_id in tenants:
            job_id = await self._queue.enqueue(
                "digest_daily",
                {"tenant_id": tenant_id, "day": str(day)},
                f"digest:{tenant_id}:{day}",
            )
            if job_id is not None:
                enqueued += 1
        logger.info("digest.scheduled", day=str(day), tenants=len(tenants), enqueued=enqueued)
        return enqueued

    def start(self) -> None:
        """Start the midnight loop as a background task."""
        self._task = asyncio.create_task(self._run(), name="neuralgram-digest-scheduler")

    async def stop(self) -> None:
        """Cancel the midnight loop."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            now = datetime.now(tz=UTC)
            await asyncio.sleep((next_midnight_utc(now) - now).total_seconds())
            await self.tick(datetime.now(tz=UTC))
