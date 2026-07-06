"""C2.2 durable job queue: Postgres-backed with SKIP LOCKED claims.

Semantics (spec C2.2): every job has kind, payload, unique dedupe key,
retry count, lease (owner + expiry), and run_after. Claims are atomic
(`FOR UPDATE SKIP LOCKED`); an expired lease makes the job claimable
again, so worker crashes never lose admitted work.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neuralgram.observability import metrics
from neuralgram.storage.models import Job

DEFAULT_LEASE_SECONDS = 60
DEFAULT_MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 30


class ClaimedJob(BaseModel):
    """A leased job handed to a worker."""

    id: str
    kind: str
    payload: dict[str, Any]
    retry_count: int


def _now() -> datetime:
    return datetime.now(tz=UTC)


class JobQueue:
    """Durable queue over the `jobs` table."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._session_factory = session_factory
        self._max_retries = max_retries

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        dedupe_key: str,
        run_after: datetime | None = None,
    ) -> str | None:
        """Insert a job unless `dedupe_key` already exists; returns the new job id or None."""
        statement = (
            insert(Job)
            .values(
                id=uuid.uuid4().hex,
                kind=kind,
                payload=payload,
                dedupe_key=dedupe_key,
                retry_count=0,
                run_after=run_after,
                status="queued",
            )
            .on_conflict_do_nothing(constraint="uq_jobs_dedupe_key")
            .returning(Job.id)
        )
        async with self._session_factory() as session:
            job_id = (await session.execute(statement)).scalar_one_or_none()
            await session.commit()
        return job_id

    async def claim(
        self,
        worker_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> ClaimedJob | None:
        """Atomically lease the oldest runnable job; None when queue is empty.

        Runnable = status 'queued' with run_after due, or 'leased' with an
        expired lease (crash recovery). Concurrent claimers never receive
        the same job (SKIP LOCKED).
        """
        now = _now()
        candidate = (
            select(Job.id)
            .where(
                or_(
                    Job.status == "queued",
                    (Job.status == "leased") & (Job.lease_expires_at < now),
                ),
                or_(Job.run_after.is_(None), Job.run_after <= now),
            )
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        async with self._session_factory() as session:
            job_id = (await session.execute(candidate)).scalar_one_or_none()
            if job_id is None:
                await session.rollback()
                return None
            statement = (
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status="leased",
                    lease_owner=worker_id,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                )
                .returning(Job.id, Job.kind, Job.payload, Job.retry_count)
            )
            row = (await session.execute(statement)).one()
            await session.commit()
        return ClaimedJob(id=row[0], kind=row[1], payload=row[2], retry_count=row[3])

    async def ack(self, job_id: str) -> None:
        """Mark a leased job done and release its lease."""
        async with self._session_factory() as session:
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(status="done", lease_owner=None, lease_expires_at=None)
            )
            await session.commit()

    async def fail(self, job_id: str) -> str:
        """Record a failure: requeue with backoff, or mark 'failed' when retries are exhausted.

        Returns the resulting status ('queued' or 'failed').
        """
        async with self._session_factory() as session:
            retry_count, kind = (
                await session.execute(select(Job.retry_count, Job.kind).where(Job.id == job_id))
            ).one()
            if retry_count + 1 >= self._max_retries:
                values: dict[str, Any] = {"status": "failed"}
                metrics.jobs_failed_total.labels(kind).inc()
            else:
                values = {
                    "status": "queued",
                    "run_after": _now() + timedelta(seconds=RETRY_BACKOFF_SECONDS),
                }
            values |= {
                "retry_count": retry_count + 1,
                "lease_owner": None,
                "lease_expires_at": None,
            }
            await session.execute(update(Job).where(Job.id == job_id).values(**values))
            await session.commit()
            return str(values["status"])
