"""C2.4 source summary trees: L0 buffer -> seal L1 -> cascade L2... (M3-1).

Leaf lifecycle: admitted -> buffered -> sealed. A summary node is "open"
until a higher-level node consumes it (`sealed_at` set). Summarization
goes through the gateway (`hint:summarize`) on C3-compressed input; tests
assert structure and state transitions, never prose (standards §4).
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neuralgram.compression.engine import compress
from neuralgram.observability.logging import get_logger
from neuralgram.router.gateway import Message, ModelGateway
from neuralgram.storage.models import Chunk, Summary

DEFAULT_BUFFER_SIZE = 8
DEFAULT_CASCADE_SIZE = 4
SUMMARY_BUDGET_TOKENS = 1500

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


class SourceTree:
    """Maintains per-(tenant, source) summary trees over admitted chunks."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: ModelGateway,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        cascade_size: int = DEFAULT_CASCADE_SIZE,
    ) -> None:
        self._session_factory = session_factory
        self._gateway = gateway
        self._buffer_size = buffer_size
        self._cascade_size = cascade_size

    async def append_buffer(self, payload: dict[str, Any]) -> None:
        """Handler for `append_buffer` jobs; payload = {"chunk_id": ...}.

        Marks an admitted chunk 'buffered'; seals the buffer when full.
        """
        chunk_id = payload["chunk_id"]
        async with self._session_factory() as session:
            chunk = await session.get(Chunk, chunk_id)
            if chunk is None or chunk.lifecycle != "admitted":
                logger.info("tree.append_skipped", chunk_id=chunk_id)
                return
            await session.execute(
                update(Chunk).where(Chunk.id == chunk_id).values(lifecycle="buffered")
            )
            await session.commit()
            tenant_id, source_id = chunk.tenant_id, chunk.source_id

        if await self._buffered_count(tenant_id, source_id) >= self._buffer_size:
            await self.seal(tenant_id, source_id)

    async def seal(self, tenant_id: str, source_id: str) -> str | None:
        """Seal the current L0 buffer into an L1 summary node; cascade upward.

        Returns the new summary id, or None when the buffer is empty.
        """
        async with self._session_factory() as session:
            buffered = (
                (
                    await session.execute(
                        select(Chunk)
                        .where(
                            Chunk.tenant_id == tenant_id,
                            Chunk.source_id == source_id,
                            Chunk.lifecycle == "buffered",
                        )
                        .order_by(Chunk.created_at)
                        .limit(self._buffer_size)
                    )
                )
                .scalars()
                .all()
            )
            if not buffered:
                return None

            body = await self._summarize([c.content_md for c in buffered])
            summary_id = uuid.uuid4().hex
            session.add(
                Summary(
                    id=summary_id,
                    tenant_id=tenant_id,
                    tree_type="source",
                    scope_id=source_id,
                    level=1,
                    body_md=body,
                    child_ids={"chunks": [c.id for c in buffered]},
                )
            )
            await session.execute(
                update(Chunk)
                .where(Chunk.id.in_([c.id for c in buffered]))
                .values(lifecycle="sealed")
            )
            await session.commit()

        await self._cascade(tenant_id, source_id, level=1)
        logger.info("tree.sealed", tenant=tenant_id, source=source_id, summary=summary_id)
        return summary_id

    async def flush_stale(self, payload: dict[str, Any]) -> None:
        """Handler for `flush_stale` jobs: seal partial buffers older than max_age_seconds."""
        tenant_id = payload["tenant_id"]
        source_id = payload["source_id"]
        max_age = timedelta(seconds=payload.get("max_age_seconds", 3600))
        async with self._session_factory() as session:
            oldest = (
                await session.execute(
                    select(func.min(Chunk.created_at)).where(
                        Chunk.tenant_id == tenant_id,
                        Chunk.source_id == source_id,
                        Chunk.lifecycle == "buffered",
                    )
                )
            ).scalar_one_or_none()
        if oldest is not None and oldest <= _now() - max_age:
            await self.seal(tenant_id, source_id)

    async def _buffered_count(self, tenant_id: str, source_id: str) -> int:
        async with self._session_factory() as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(Chunk)
                    .where(
                        Chunk.tenant_id == tenant_id,
                        Chunk.source_id == source_id,
                        Chunk.lifecycle == "buffered",
                    )
                )
            ).scalar_one()
        return int(count)

    async def _cascade(self, tenant_id: str, scope_id: str, level: int) -> None:
        """Fold `cascade_size` open level-N nodes into one level-N+1 node, repeatedly."""
        while True:
            async with self._session_factory() as session:
                open_nodes = (
                    (
                        await session.execute(
                            select(Summary)
                            .where(
                                Summary.tenant_id == tenant_id,
                                Summary.tree_type == "source",
                                Summary.scope_id == scope_id,
                                Summary.level == level,
                                Summary.sealed_at.is_(None),
                            )
                            .order_by(Summary.id)
                            .limit(self._cascade_size)
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(open_nodes) < self._cascade_size:
                    return

                body = await self._summarize([n.body_md for n in open_nodes])
                parent_id = uuid.uuid4().hex
                session.add(
                    Summary(
                        id=parent_id,
                        tenant_id=tenant_id,
                        tree_type="source",
                        scope_id=scope_id,
                        level=level + 1,
                        body_md=body,
                        child_ids={"summaries": [n.id for n in open_nodes]},
                    )
                )
                await session.execute(
                    update(Summary)
                    .where(Summary.id.in_([n.id for n in open_nodes]))
                    .values(sealed_at=_now())
                )
                await session.commit()
            level += 1

    async def _summarize(self, bodies: list[str]) -> str:
        joined = "\n\n---\n\n".join(bodies)
        compressed = compress(joined, SUMMARY_BUDGET_TOKENS)
        reply = await self._gateway.complete(
            [Message(role="user", content=f"Summarize:\n\n{compressed.text}")],
            "hint:summarize",
        )
        # Deterministic content marker so identical inputs yield identical nodes.
        digest = hashlib.sha256(joined.encode()).hexdigest()[:12]
        return f"{reply.text}\n<!-- children-digest:{digest} -->"
