"""Integration: storage tables exist and content_hash dedupe is enforced (M1-1 acceptance)."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from neuralgram.storage.models import Chunk

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {"chunks", "scores", "entities", "chunk_entities", "summaries", "jobs"}


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


def _chunk(chunk_id: str, content_hash: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        tenant_id="tenant-a",
        source_id="slack:C123",
        content_md="hello world",
        token_count=2,
        provenance={"source": "slack", "author": "u1", "ts": "2026-07-06T00:00:00Z"},
        lifecycle="pending_extraction",
        content_hash=content_hash,
    )


async def test_all_tables_are_created(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = {row[0] for row in rows}
    assert tables >= EXPECTED_TABLES


async def test_duplicate_content_hash_is_rejected(engine: AsyncEngine) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(_chunk("id-1", "hash-dupe"))
        await session.commit()

    async with factory() as session:
        session.add(_chunk("id-2", "hash-dupe"))
        with pytest.raises(IntegrityError, match="uq_chunks_content_hash"):
            await session.commit()
        await session.rollback()


async def test_downgrade_removes_tables(async_url: str) -> None:
    env = os.environ | {"DATABASE_URL": async_url}
    down = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0001"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert down.returncode == 0, down.stderr

    engine = create_async_engine(async_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            tables = {row[0] for row in rows}
    finally:
        await engine.dispose()
    assert not (EXPECTED_TABLES & tables)

    up_again = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert up_again.returncode == 0, up_again.stderr
