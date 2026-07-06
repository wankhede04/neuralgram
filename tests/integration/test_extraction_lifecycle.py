"""Integration: extract_chunk lifecycle transitions on real Postgres (M2-4 acceptance)."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from neuralgram.common.config import Settings
from neuralgram.ingestion.canonicalize import CanonicalDoc, Provenance
from neuralgram.memory.chunker import chunk
from neuralgram.memory.extraction import Extractor
from neuralgram.memory.store import ContentStore
from neuralgram.router.gateway import build_gateway
from neuralgram.storage.models import Chunk, ChunkEntity, Score

REPO_ROOT = Path(__file__).resolve().parents[2]

RICH_BODY = (
    "Deploy for the Neuralgram memory service lands Friday. Alice Chen owns the "
    "migration checklist and Postgres rollback rehearsal for the vault store."
)
TRIVIAL_BODY = "ok ok ok ok"


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
async def engine(async_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(async_url)
    try:
        yield engine
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


async def _seed(engine: AsyncEngine, tmp_path: Path, tenant: str, body: str) -> str:
    store = ContentStore(async_sessionmaker(engine, expire_on_commit=False), tmp_path)
    result = await store.persist(chunk(_doc(body), tenant))
    assert len(result.inserted_ids) == 1
    return result.inserted_ids[0]


async def test_rich_chunk_is_admitted_with_scores_entities_embedding(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chunk_id = await _seed(engine, tmp_path, "tenant-admit", RICH_BODY)

    extractor = Extractor(factory, build_gateway(Settings(_env_file=None)))
    await extractor.extract_chunk({"chunk_id": chunk_id})

    async with factory() as session:
        row = await session.get(Chunk, chunk_id)
        assert row is not None and row.lifecycle == "admitted"

        score = await session.get(Score, chunk_id)
        assert score is not None
        assert score.deep_score is not None and score.deep_score >= 0.3
        assert score.embedding is not None and len(list(score.embedding)) == 384

        links = (
            (await session.execute(select(ChunkEntity).where(ChunkEntity.chunk_id == chunk_id)))
            .scalars()
            .all()
        )
        assert links, "admitted chunk must link extracted entities"


async def test_trivial_chunk_is_dropped_but_provenance_row_survives(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chunk_id = await _seed(engine, tmp_path, "tenant-drop", TRIVIAL_BODY)

    extractor = Extractor(factory, build_gateway(Settings(_env_file=None)))
    await extractor.extract_chunk({"chunk_id": chunk_id})

    async with factory() as session:
        row = await session.get(Chunk, chunk_id)
        assert row is not None, "dropped chunk row must be retained"
        assert row.lifecycle == "dropped"
        assert row.provenance["author"] == "U01ALICE", "provenance survives the drop"

        links = (
            (await session.execute(select(ChunkEntity).where(ChunkEntity.chunk_id == chunk_id)))
            .scalars()
            .all()
        )
        assert links == [], "dropped chunks link no entities"


async def test_reprocessing_admitted_chunk_is_a_noop(engine: AsyncEngine, tmp_path: Path) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chunk_id = await _seed(engine, tmp_path, "tenant-noop", RICH_BODY)

    extractor = Extractor(factory, build_gateway(Settings(_env_file=None)))
    await extractor.extract_chunk({"chunk_id": chunk_id})
    await extractor.extract_chunk({"chunk_id": chunk_id})  # second run: lifecycle != pending

    async with factory() as session:
        row = await session.get(Chunk, chunk_id)
        assert row is not None and row.lifecycle == "admitted"
