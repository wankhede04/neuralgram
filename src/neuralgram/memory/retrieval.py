"""C2.5 retrieval: lexical search and fetch-by-id, always tenant-scoped,
always with provenance (spec guarantee: every result links back to its source)."""

from typing import Any

from pydantic import BaseModel
from sqlalchemy import Float, cast, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from neuralgram.storage.models import Chunk, Score
from neuralgram.storage.repository import TenantScopedRepository


class RetrievedChunk(BaseModel):
    """A retrieval result: content plus the provenance trail back to its source."""

    chunk_id: str
    source_id: str
    content_md: str
    token_count: int
    lifecycle: str
    provenance: dict[str, Any]
    rank: float | None = None


def _to_result(chunk: Chunk, rank: float | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        source_id=chunk.source_id,
        content_md=chunk.content_md,
        token_count=chunk.token_count,
        lifecycle=chunk.lifecycle,
        provenance=chunk.provenance,
        rank=rank,
    )


class ChunkRetrieval(TenantScopedRepository[Chunk]):
    """Tenant-scoped lexical retrieval over chunks."""

    model = Chunk

    async def search(
        self, session: AsyncSession, query: str, limit: int = 10
    ) -> list[RetrievedChunk]:
        """Full-text search over `content_md`, ranked, tenant-scoped.

        Returns up to `limit` chunks; each carries provenance and rank.
        """
        ts_vector = func.to_tsvector("english", Chunk.content_md)
        ts_query = func.plainto_tsquery("english", query)
        rank = cast(func.ts_rank(ts_vector, ts_query), Float)
        statement = (
            self.scoped_select()
            .add_columns(rank.label("rank"))
            .where(ts_vector.op("@@")(ts_query))
            .order_by(desc("rank"))
            .limit(limit)
        )
        rows = await session.execute(statement)
        return [_to_result(row[0], float(row[1])) for row in rows]

    async def fetch(self, session: AsyncSession, chunk_id: str) -> RetrievedChunk | None:
        """Fetch one chunk by id within this tenant; None if absent or foreign."""
        statement = self.scoped_select().where(Chunk.id == chunk_id)
        row = (await session.execute(statement)).scalar_one_or_none()
        return _to_result(row) if row is not None else None

    async def semantic_search(
        self, session: AsyncSession, query_vector: list[float], limit: int = 10
    ) -> list[RetrievedChunk]:
        """Nearest-neighbor search over chunk embeddings (cosine), tenant-scoped."""
        distance = Score.embedding.cosine_distance(query_vector)
        statement = (
            self.scoped_select()
            .join(Score, Score.chunk_id == Chunk.id)
            .where(Score.embedding.is_not(None))
            .add_columns((1 - distance).label("rank"))
            .order_by(distance)
            .limit(limit)
        )
        rows = await session.execute(statement)
        return [_to_result(row[0], float(row[1])) for row in rows]

    async def hybrid_search(
        self,
        session: AsyncSession,
        query: str,
        query_vector: list[float],
        limit: int = 10,
        rrf_k: int = 60,
    ) -> list[RetrievedChunk]:
        """Keyword + semantic fusion via reciprocal rank fusion (RRF).

        Each result's rank is `sum(1 / (rrf_k + position))` across the two
        result lists, so a chunk missed by one retriever can still win.
        """
        keyword = await self.search(session, query, limit)
        semantic = await self.semantic_search(session, query_vector, limit)

        fused: dict[str, float] = {}
        by_id: dict[str, RetrievedChunk] = {}
        for results in (keyword, semantic):
            for position, result in enumerate(results):
                fused[result.chunk_id] = fused.get(result.chunk_id, 0.0) + 1.0 / (
                    rrf_k + position + 1
                )
                by_id.setdefault(result.chunk_id, result)
        ranked = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:limit]
        return [by_id[cid].model_copy(update={"rank": fused[cid]}) for cid in ranked]
