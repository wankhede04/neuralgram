"""Integration: gateway embeddings persist to pgvector and are queryable (M2-3 acceptance)."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from neuralgram.common.config import Settings
from neuralgram.ingestion.canonicalize import CanonicalDoc, Provenance
from neuralgram.memory.chunker import chunk
from neuralgram.memory.embeddings import persist_embeddings
from neuralgram.memory.store import ContentStore
from neuralgram.router.gateway import build_gateway
from neuralgram.storage.models import Score

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def async_url() -> Iterator[str]:
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=os.environ | {"DATABASE_URL": url},
            capture_output=True,
            text=True,
        )
        assert upgrade.returncode == 0, upgrade.stderr
        yield url


@pytest.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def _doc(body: str) -> CanonicalDoc:
    return CanonicalDoc(
        body_md=body,
        provenance=Provenance(
            source_type="slack",
            source_id="C042MEMORY",
            external_id="1783296000.000100",
            author="U01ALICE",
            timestamp=datetime(2026, 7, 6, tzinfo=UTC),
        ),
        source_type="slack",
    )


async def test_embeddings_persist_and_similarity_query_works(
    async_url: str, session: AsyncSession, tmp_path: Path
) -> None:
    settings = Settings(_env_file=None)
    gateway = build_gateway(settings)

    engine = create_async_engine(async_url)
    store = ContentStore(async_sessionmaker(engine, expire_on_commit=False), tmp_path)
    drafts = [
        d
        for body in ("deploy the memory service", "unrelated lunch plans")
        for d in chunk(_doc(body), "tenant-embed")
    ]
    await store.persist(drafts)
    await engine.dispose()

    vectors = await gateway.embed([d.content_md for d in drafts])
    written = await persist_embeddings(
        session, {d.id: v for d, v in zip(drafts, vectors, strict=True)}, "tenant-embed"
    )
    await session.commit()
    assert written == len(drafts)

    stored = (await session.execute(select(Score.embedding))).scalars().all()
    assert len(stored) >= len(drafts)
    assert all(len(list(v)) == settings.embedding_dim for v in stored)

    # Same text embeds to the same vector -> nearest neighbor is its own chunk.
    probe = (await gateway.embed([drafts[0].content_md]))[0]
    nearest = (
        await session.execute(
            select(Score.chunk_id).order_by(Score.embedding.cosine_distance(probe)).limit(1)
        )
    ).scalar_one()
    assert nearest == drafts[0].id

    # Upsert: re-persisting the same chunk overwrites, not duplicates.
    again = await persist_embeddings(session, {drafts[0].id: vectors[0]}, "tenant-embed")
    await session.commit()
    assert again == 1
    count = len((await session.execute(select(Score.chunk_id))).scalars().all())
    assert count == len(drafts)
