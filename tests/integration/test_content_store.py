"""Integration: hot-path persist is atomic and idempotent (M1-4 acceptance)."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from neuralgram.ingestion.canonicalize import CanonicalDoc, Provenance
from neuralgram.memory.chunker import ChunkDraft, chunk
from neuralgram.memory.store import ContentStore
from neuralgram.storage.models import Chunk

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
async def engine(async_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(async_url)
    try:
        yield engine
    finally:
        await engine.dispose()


def _drafts(tenant_id: str, body: str) -> list[ChunkDraft]:
    doc = CanonicalDoc(
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
    return chunk(doc, tenant_id, max_tokens=50)


async def _row_count(engine: AsyncEngine, tenant_id: str) -> int:
    async with engine.connect() as connection:
        result = await connection.execute(
            select(func.count()).select_from(Chunk).where(Chunk.tenant_id == tenant_id)
        )
        return int(result.scalar_one())


async def test_persist_writes_rows_and_vault_files(engine: AsyncEngine, tmp_path: Path) -> None:
    store = ContentStore(async_sessionmaker(engine, expire_on_commit=False), tmp_path)
    drafts = _drafts("tenant-persist", "first paragraph\n\nsecond paragraph")

    result = await store.persist(drafts)

    assert result.inserted == len(drafts) > 0
    assert await _row_count(engine, "tenant-persist") == len(drafts)
    for draft in drafts:
        path = store.vault_file(draft.tenant_id, draft.id)
        assert path.is_file()
        assert path.read_text(encoding="utf-8") == draft.content_md

    async with engine.connect() as connection:
        lifecycles = await connection.execute(
            select(Chunk.lifecycle).where(Chunk.tenant_id == "tenant-persist")
        )
        assert {row[0] for row in lifecycles} == {"pending_extraction"}


async def test_reingest_is_idempotent(engine: AsyncEngine, tmp_path: Path) -> None:
    store = ContentStore(async_sessionmaker(engine, expire_on_commit=False), tmp_path)
    drafts = _drafts("tenant-idem", "alpha\n\nbeta\n\ngamma")

    first = await store.persist(drafts)
    second = await store.persist(drafts)

    assert first.inserted == len(drafts)
    assert second.inserted == 0
    assert second.skipped == len(drafts)
    assert await _row_count(engine, "tenant-idem") == len(drafts)


async def test_partial_failure_leaves_no_dangling_rows_or_files(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ContentStore(async_sessionmaker(engine, expire_on_commit=False), tmp_path)
    paragraphs = [f"paragraph {i}: " + ("lorem ipsum dolor sit amet " * 6) for i in range(4)]
    drafts = _drafts("tenant-crash", "\n\n".join(paragraphs))
    assert len(drafts) >= 2

    original = ContentStore._write_vault_file
    calls = {"n": 0}

    def crash_on_second(self: ContentStore, draft: ChunkDraft) -> Path:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated disk failure")
        return original(self, draft)

    monkeypatch.setattr(ContentStore, "_write_vault_file", crash_on_second)
    with pytest.raises(OSError, match="simulated disk failure"):
        await store.persist(drafts)

    assert await _row_count(engine, "tenant-crash") == 0, "no dangling rows"
    tenant_dir = tmp_path / "tenant-crash"
    leftover = list(tenant_dir.rglob("*.md")) if tenant_dir.exists() else []
    assert leftover == [], "no dangling vault files"
