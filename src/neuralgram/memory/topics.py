"""C2.4 topic trees: materialized per hot entity, gated by a hotness threshold."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neuralgram.compression.engine import compress
from neuralgram.memory.hotness import hotness
from neuralgram.observability.logging import get_logger
from neuralgram.router.gateway import Message, ModelGateway
from neuralgram.storage.models import Chunk, ChunkEntity, Entity, Summary

DEFAULT_HOTNESS_THRESHOLD = 3.0
TOPIC_SUMMARY_BUDGET_TOKENS = 1500

logger = get_logger(__name__)


class TopicRouter:
    """Recomputes entity hotness on mention and materializes hot topic trees."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: ModelGateway,
        threshold: float = DEFAULT_HOTNESS_THRESHOLD,
    ) -> None:
        self._session_factory = session_factory
        self._gateway = gateway
        self._threshold = threshold

    async def topic_route(self, payload: dict[str, Any]) -> None:
        """Handler for `topic_route` jobs; payload = {"entity_id": ...}.

        Updates the entity's hotness; creates/refreshes the topic tree node
        only when hotness exceeds the threshold.
        """
        entity_id = payload["entity_id"]
        now = datetime.now(tz=UTC)
        async with self._session_factory() as session:
            entity = await session.get(Entity, entity_id)
            if entity is None:
                logger.info("topic.skipped", entity_id=entity_id)
                return

            mention_rows = (
                await session.execute(
                    select(Chunk.id, Chunk.created_at, Chunk.content_md)
                    .join(ChunkEntity, ChunkEntity.chunk_id == Chunk.id)
                    .where(ChunkEntity.entity_id == entity_id)
                    .order_by(Chunk.created_at)
                )
            ).all()
            score = hotness([row[1] for row in mention_rows], now)
            await session.execute(
                update(Entity).where(Entity.id == entity_id).values(hotness=score)
            )

            if score <= self._threshold:
                await session.commit()
                logger.info("topic.below_threshold", entity_id=entity_id, hotness=score)
                return

            body = await self._summarize([row[2] for row in mention_rows], entity.tenant_id)
            existing = (
                await session.execute(
                    select(Summary).where(
                        Summary.tenant_id == entity.tenant_id,
                        Summary.tree_type == "topic",
                        Summary.scope_id == entity_id,
                        Summary.level == 1,
                    )
                )
            ).scalar_one_or_none()
            child_ids = {"chunks": [row[0] for row in mention_rows]}
            if existing is None:
                session.add(
                    Summary(
                        id=uuid.uuid4().hex,
                        tenant_id=entity.tenant_id,
                        tree_type="topic",
                        scope_id=entity_id,
                        level=1,
                        body_md=body,
                        child_ids=child_ids,
                    )
                )
            else:
                existing.body_md = body
                existing.child_ids = child_ids
            await session.commit()
            logger.info("topic.materialized", entity_id=entity_id, hotness=score)

    async def _summarize(self, bodies: list[str], tenant_id: str) -> str:
        compressed = compress("\n\n---\n\n".join(bodies), TOPIC_SUMMARY_BUDGET_TOKENS)
        reply = await self._gateway.complete(
            [Message(role="user", content=f"Summarize this topic:\n\n{compressed.text}")],
            "hint:summarize",
            tenant_id=tenant_id,
        )
        return reply.text
