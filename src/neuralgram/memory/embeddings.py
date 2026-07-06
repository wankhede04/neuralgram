"""Embedding persistence (C4 embed path -> C6 pgvector storage).

Embeddings always come through the model gateway (`hint:embed` semantics);
this module only writes them to the `scores` table.
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from neuralgram.storage.models import Score


async def persist_embeddings(
    session: AsyncSession, embeddings: dict[str, list[float]], tenant_id: str
) -> int:
    """Upsert `chunk_id -> vector` pairs into scores.embedding; returns row count.

    Does not commit — callers own the transaction so embedding writes can
    join larger units of work.
    """
    if not embeddings:
        return 0
    statement = insert(Score).values(
        [
            {"chunk_id": chunk_id, "embedding": vector, "tenant_id": tenant_id}
            for chunk_id, vector in embeddings.items()
        ]
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Score.chunk_id],
        set_={"embedding": statement.excluded.embedding},
    )
    await session.execute(statement)
    return len(embeddings)
