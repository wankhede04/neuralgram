"""Integration: deterministic seal-cascade behavior (M3-1 acceptance).

All assertions are on structure and state transitions (node levels,
children, lifecycles), never on summary prose (standards §4).
"""

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
from neuralgram.memory.chunker import chunk as make_chunks
from neuralgram.memory.store import ContentStore
from neuralgram.memory.trees import SourceTree
from neuralgram.router.gateway import build_gateway
from neuralgram.storage.models import Chunk, Summary

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = "C042MEMORY"


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


async def _seed_admitted(engine: AsyncEngine, tmp_path: Path, tenant: str, index: int) -> str:
    """Persist one unique admitted chunk for `tenant`; returns its id."""
    doc = CanonicalDoc(
        body_md=f"note {index}: deploy checkpoint alpha-{index} for the memory service",
        provenance=Provenance(
            source_type="slack",
            source_id=SOURCE,
            external_id=f"ts-{index}",
            author="U01ALICE",
            timestamp=datetime(2026, 7, 6, tzinfo=UTC),
        ),
        source_type="slack",
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    store = ContentStore(factory, tmp_path)
    drafts = make_chunks(doc, tenant)
    assert len(drafts) == 1
    await store.persist(drafts)
    async with factory() as session:
        row = await session.get(Chunk, drafts[0].id)
        assert row is not None
        row.lifecycle = "admitted"
        await session.commit()
    return drafts[0].id


def _tree(engine: AsyncEngine, buffer_size: int, cascade_size: int) -> SourceTree:
    return SourceTree(
        async_sessionmaker(engine, expire_on_commit=False),
        build_gateway(Settings(_env_file=None)),
        buffer_size=buffer_size,
        cascade_size=cascade_size,
    )


async def _summaries(engine: AsyncEngine, tenant: str, level: int) -> list[Summary]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(Summary)
                    .where(
                        Summary.tenant_id == tenant,
                        Summary.tree_type == "source",
                        Summary.level == level,
                    )
                    .order_by(Summary.id)
                )
            )
            .scalars()
            .all()
        )


async def test_buffer_fill_triggers_seal_and_chunks_become_sealed(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    tenant = "tenant-seal"
    tree = _tree(engine, buffer_size=3, cascade_size=99)
    ids = [await _seed_admitted(engine, tmp_path, tenant, i) for i in range(3)]

    for chunk_id in ids[:2]:
        await tree.append_buffer({"chunk_id": chunk_id})
    assert await _summaries(engine, tenant, level=1) == [], "no seal before the buffer fills"

    await tree.append_buffer({"chunk_id": ids[2]})
    level1 = await _summaries(engine, tenant, level=1)
    assert len(level1) == 1, "buffer full -> exactly one L1 seal"
    assert set(level1[0].child_ids["chunks"]) == set(ids)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        lifecycles = {
            row.lifecycle
            for row in (
                (await session.execute(select(Chunk).where(Chunk.id.in_(ids)))).scalars().all()
            )
        }
    assert lifecycles == {"sealed"}


async def test_cascade_folds_open_nodes_upward(engine: AsyncEngine, tmp_path: Path) -> None:
    tenant = "tenant-cascade"
    tree = _tree(engine, buffer_size=1, cascade_size=2)

    for i in range(4):  # each chunk seals to L1; pairs cascade to L2; two L2 -> L3
        await tree.append_buffer({"chunk_id": await _seed_admitted(engine, tmp_path, tenant, i)})

    level1 = await _summaries(engine, tenant, level=1)
    level2 = await _summaries(engine, tenant, level=2)
    level3 = await _summaries(engine, tenant, level=3)

    assert len(level1) == 4
    assert all(node.sealed_at is not None for node in level1), "all L1 consumed by L2"
    assert len(level2) == 2
    assert all(node.sealed_at is not None for node in level2), "all L2 consumed by L3"
    assert len(level3) == 1
    assert level3[0].sealed_at is None, "the root stays open"
    assert set(level3[0].child_ids["summaries"]) == {n.id for n in level2}


async def test_flush_stale_seals_partial_buffer(engine: AsyncEngine, tmp_path: Path) -> None:
    tenant = "tenant-stale"
    tree = _tree(engine, buffer_size=99, cascade_size=99)
    chunk_id = await _seed_admitted(engine, tmp_path, tenant, 0)
    await tree.append_buffer({"chunk_id": chunk_id})
    assert await _summaries(engine, tenant, level=1) == []

    await tree.flush_stale({"tenant_id": tenant, "source_id": SOURCE, "max_age_seconds": 0})
    level1 = await _summaries(engine, tenant, level=1)
    assert len(level1) == 1
    assert level1[0].child_ids["chunks"] == [chunk_id]


async def test_identical_inputs_yield_identical_children_digest(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    """Determinism fixture: same content in two tenants -> same digest marker."""
    tree_a = _tree(engine, buffer_size=1, cascade_size=99)
    a = await _seed_admitted(engine, tmp_path, "tenant-det-a", 42)
    b = await _seed_admitted(engine, tmp_path, "tenant-det-b", 42)
    await tree_a.append_buffer({"chunk_id": a})
    await tree_a.append_buffer({"chunk_id": b})

    digest_a = (await _summaries(engine, "tenant-det-a", 1))[0].body_md.split("children-digest:")[1]
    digest_b = (await _summaries(engine, "tenant-det-b", 1))[0].body_md.split("children-digest:")[1]
    assert digest_a == digest_b
