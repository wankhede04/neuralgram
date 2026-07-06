"""Integration: lexical search + fetch with provenance, tenant-scoped (M1-6 acceptance)."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from neuralgram.ingestion.canonicalize import ingest
from neuralgram.memory.chunker import chunk
from neuralgram.memory.retrieval import ChunkRetrieval
from neuralgram.memory.store import ContentStore

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "slack_export_sample.json"


@pytest.fixture(scope="module")
def async_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
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


@pytest.fixture(scope="module")
def seeded(async_url: str, tmp_path_factory: pytest.TempPathFactory) -> str:
    """Ingest the Slack fixture for tenant-a via the real C1->C2.1 path."""
    import asyncio
    import json

    async def _seed() -> None:
        engine = create_async_engine(async_url)
        store = ContentStore(
            async_sessionmaker(engine, expire_on_commit=False),
            tmp_path_factory.mktemp("vault"),
        )
        docs = ingest("C042MEMORY", json.loads(FIXTURE.read_text()))
        for doc in docs:
            await store.persist(chunk(doc, "tenant-a"))
        await engine.dispose()

    asyncio.run(_seed())
    return "tenant-a"


async def test_search_returns_chunks_with_source_links(seeded: str, session: AsyncSession) -> None:
    results = await ChunkRetrieval(seeded).search(session, "migration checklist")
    assert results, "expected a hit for 'migration checklist'"
    top = results[0]
    assert "migration checklist" in top.content_md
    assert top.source_id == "C042MEMORY"
    assert top.provenance["source_type"] == "slack"
    assert top.provenance["author"] == "U01ALICE"
    assert top.provenance["url"].startswith("https://example.slack.com")
    assert top.rank is not None and top.rank > 0


async def test_fetch_returns_provenance(seeded: str, session: AsyncSession) -> None:
    retrieval = ChunkRetrieval(seeded)
    results = await retrieval.search(session, "migration checklist")
    fetched = await retrieval.fetch(session, results[0].chunk_id)
    assert fetched is not None
    assert fetched.provenance["external_id"] == "1783296000.000100"
    assert fetched.provenance["timestamp"].startswith("2026-07-06")


async def test_other_tenant_sees_nothing(seeded: str, session: AsyncSession) -> None:
    other = ChunkRetrieval("tenant-b")
    assert await other.search(session, "migration checklist") == []

    mine = await ChunkRetrieval(seeded).search(session, "migration checklist")
    assert await other.fetch(session, mine[0].chunk_id) is None
