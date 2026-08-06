"""GDPR erasure (C7, M5-3): cascade delete of a tenant's memory.

Removes chunks, scores (embeddings included), entity links, entities,
summaries, vault files, queue jobs referencing the erased data, and the
signup identity row (which holds the tenant's email).
`usage_events` and `audit_events` are deliberately retained: billing and
security records fall under legitimate-interest retention, and they carry
no memory content.
"""

import shutil
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neuralgram.observability.logging import get_logger
from neuralgram.storage.models import Chunk, ChunkEntity, Entity, Job, Score, Summary, User

logger = get_logger(__name__)


def _deleted(result: object) -> int:
    """Rows removed by a DELETE (CursorResult.rowcount, typed loosely by SQLAlchemy)."""
    return int(getattr(result, "rowcount", 0) or 0)


class ErasureReport(BaseModel):
    """What one erasure removed."""

    chunks: int
    scores: int
    chunk_entities: int
    entities: int
    summaries: int
    jobs: int
    users: int
    vault_files: int


class ErasureService:
    """Cascade-deletes everything a tenant's memory produced."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], vault_root: Path) -> None:
        self._session_factory = session_factory
        self._vault_root = vault_root

    async def erase_tenant(self, tenant_id: str) -> ErasureReport:
        """Erase all of `tenant_id`'s memory in one transaction + vault sweep.

        Returns per-table counts. The DB deletion commits before vault
        files are removed, so a crash can leave orphan files (re-run the
        erasure) but never dangling rows.
        """
        async with self._session_factory() as session:
            chunk_ids = set(
                (await session.execute(select(Chunk.id).where(Chunk.tenant_id == tenant_id)))
                .scalars()
                .all()
            )
            entity_ids = set(
                (await session.execute(select(Entity.id).where(Entity.tenant_id == tenant_id)))
                .scalars()
                .all()
            )

            links = await session.execute(
                delete(ChunkEntity).where(ChunkEntity.tenant_id == tenant_id)
            )
            scores = await session.execute(delete(Score).where(Score.tenant_id == tenant_id))
            chunks = await session.execute(delete(Chunk).where(Chunk.tenant_id == tenant_id))
            entities = await session.execute(delete(Entity).where(Entity.tenant_id == tenant_id))
            summaries = await session.execute(delete(Summary).where(Summary.tenant_id == tenant_id))
            job_conditions = [Job.payload["tenant_id"].as_string() == tenant_id]
            if chunk_ids:
                job_conditions.append(Job.payload["chunk_id"].as_string().in_(chunk_ids))
            if entity_ids:
                job_conditions.append(Job.payload["entity_id"].as_string().in_(entity_ids))
            jobs = await session.execute(delete(Job).where(or_(*job_conditions)))
            # The signup identity row holds the tenant's email — personal data.
            users = await session.execute(delete(User).where(User.tenant_id == tenant_id))
            await session.commit()

        vault_files = 0
        tenant_dir = self._vault_root / tenant_id
        if tenant_dir.exists():
            vault_files = sum(1 for _ in tenant_dir.rglob("*.md"))
            shutil.rmtree(tenant_dir)

        report = ErasureReport(
            chunks=_deleted(chunks),
            scores=_deleted(scores),
            chunk_entities=_deleted(links),
            entities=_deleted(entities),
            summaries=_deleted(summaries),
            jobs=_deleted(jobs),
            users=_deleted(users),
            vault_files=vault_files,
        )
        logger.info("erasure.done", tenant=tenant_id, **report.model_dump())
        return report
