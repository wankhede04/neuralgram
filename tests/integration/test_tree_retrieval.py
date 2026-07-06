"""Integration: tree-scoped retrieval returns correct summaries with provenance (M3-4)."""

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from neuralgram.memory.tree_retrieval import TreeRetrieval
from neuralgram.storage.models import Summary

REPO_ROOT = Path(__file__).resolve().parents[2]
TENANT = "tenant-tree-ret"
OTHER = "tenant-other"
SOURCE = "C042MEMORY"
DAY = date(2026, 7, 5)


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


@pytest.fixture(scope="module")
def seeded(async_url: str) -> dict[str, str]:
    """Seed source (L1+L2), topic, and global summary nodes for TENANT."""
    import asyncio

    ids = {
        "l1a": uuid.uuid4().hex,
        "l1b": uuid.uuid4().hex,
        "l2": uuid.uuid4().hex,
        "topic": uuid.uuid4().hex,
        "global": uuid.uuid4().hex,
        "foreign": uuid.uuid4().hex,
        "entity": "entity-hot-1",
    }

    async def _seed() -> None:
        engine = create_async_engine(async_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(tz=UTC)
        async with factory() as session:
            session.add_all(
                [
                    Summary(
                        id=ids["l1a"],
                        tenant_id=TENANT,
                        tree_type="source",
                        scope_id=SOURCE,
                        level=1,
                        body_md="l1a",
                        child_ids={"chunks": ["c1", "c2"]},
                        sealed_at=now - timedelta(hours=1),
                    ),
                    Summary(
                        id=ids["l1b"],
                        tenant_id=TENANT,
                        tree_type="source",
                        scope_id=SOURCE,
                        level=1,
                        body_md="l1b",
                        child_ids={"chunks": ["c3"]},
                        sealed_at=now - timedelta(hours=1),
                    ),
                    Summary(
                        id=ids["l2"],
                        tenant_id=TENANT,
                        tree_type="source",
                        scope_id=SOURCE,
                        level=2,
                        body_md="l2",
                        child_ids={"summaries": [ids["l1a"], ids["l1b"]]},
                    ),
                    Summary(
                        id=ids["topic"],
                        tenant_id=TENANT,
                        tree_type="topic",
                        scope_id=ids["entity"],
                        level=1,
                        body_md="topic",
                        child_ids={"chunks": ["c1", "c3"]},
                    ),
                    Summary(
                        id=ids["global"],
                        tenant_id=TENANT,
                        tree_type="global",
                        scope_id=str(DAY),
                        level=1,
                        body_md="digest",
                        child_ids={"chunks": ["c1", "c2", "c3"]},
                    ),
                    Summary(
                        id=ids["foreign"],
                        tenant_id=OTHER,
                        tree_type="source",
                        scope_id=SOURCE,
                        level=1,
                        body_md="foreign",
                        child_ids={"chunks": ["x1"]},
                    ),
                ]
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_seed())
    return ids


@pytest.fixture
async def session(async_url: str) -> AsyncIterator[object]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def test_drill_down_returns_source_nodes_root_first(
    seeded: dict[str, str], session: object
) -> None:
    nodes = await TreeRetrieval(TENANT).drill_down(session, SOURCE)  # type: ignore[arg-type]
    assert [n.level for n in nodes] == [2, 1, 1]
    root = nodes[0]
    assert root.summary_id == seeded["l2"]
    assert set(root.child_ids["summaries"]) == {seeded["l1a"], seeded["l1b"]}
    leaf_children = [set(n.child_ids["chunks"]) for n in nodes[1:]]
    assert {"c1", "c2"} in leaf_children and {"c3"} in leaf_children

    only_l1 = await TreeRetrieval(TENANT).drill_down(session, SOURCE, level=1)  # type: ignore[arg-type]
    assert all(n.level == 1 for n in only_l1) and len(only_l1) == 2


async def test_topic_scope_returns_entity_nodes(seeded: dict[str, str], session: object) -> None:
    nodes = await TreeRetrieval(TENANT).topic(session, seeded["entity"])  # type: ignore[arg-type]
    assert len(nodes) == 1
    assert nodes[0].child_ids["chunks"] == ["c1", "c3"]
    assert await TreeRetrieval(TENANT).topic(session, "never-hot") == []  # type: ignore[arg-type]


async def test_global_scope_returns_day_digest(seeded: dict[str, str], session: object) -> None:
    node = await TreeRetrieval(TENANT).global_digest(session, DAY)  # type: ignore[arg-type]
    assert node is not None
    assert node.scope_id == str(DAY)
    assert node.child_ids["chunks"] == ["c1", "c2", "c3"]
    assert await TreeRetrieval(TENANT).global_digest(session, date(2026, 1, 1)) is None  # type: ignore[arg-type]


async def test_tree_retrieval_is_tenant_scoped(seeded: dict[str, str], session: object) -> None:
    other = await TreeRetrieval(OTHER).drill_down(session, SOURCE)  # type: ignore[arg-type]
    assert [n.summary_id for n in other] == [seeded["foreign"]]
    assert await TreeRetrieval(OTHER).topic(session, seeded["entity"]) == []  # type: ignore[arg-type]
    assert await TreeRetrieval(OTHER).global_digest(session, DAY) is None  # type: ignore[arg-type]
