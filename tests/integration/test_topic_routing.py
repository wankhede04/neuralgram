"""Integration: topic tree materializes only above the hotness threshold (M3-2 acceptance)."""

import hashlib
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
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
from neuralgram.memory.topics import TopicRouter
from neuralgram.router.gateway import build_gateway
from neuralgram.storage.models import Chunk, ChunkEntity, Entity, Summary

REPO_ROOT = Path(__file__).resolve().parents[2]
TENANT = "tenant-topic"


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


async def _seed_entity_with_mentions(
    engine: AsyncEngine, name: str, mention_ages_days: list[int]
) -> str:
    """Create an entity plus one linked chunk per mention age; returns entity id."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    entity_id = hashlib.sha256(f"{TENANT}\n{name}\nunknown".encode()).hexdigest()
    now = datetime.now(tz=UTC)
    async with factory() as session:
        session.add(
            Entity(id=entity_id, tenant_id=TENANT, name=name, type="unknown", last_seen=now)
        )
        chunk_ids = []
        for age in mention_ages_days:
            chunk_id = uuid.uuid4().hex
            session.add(
                Chunk(
                    id=chunk_id,
                    tenant_id=TENANT,
                    source_id="C042MEMORY",
                    content_md=f"{name} update {chunk_id[:8]}",
                    token_count=4,
                    provenance={"source_type": "slack"},
                    lifecycle="admitted",
                    content_hash=chunk_id,
                    created_at=now - timedelta(days=age),
                )
            )
            chunk_ids.append(chunk_id)
        await session.flush()  # parents before FK links (no ORM relationships defined)
        for chunk_id in chunk_ids:
            session.add(ChunkEntity(chunk_id=chunk_id, entity_id=entity_id, tenant_id=TENANT))
        await session.commit()
    return entity_id


async def _topic_nodes(engine: AsyncEngine, entity_id: str) -> list[Summary]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(Summary).where(
                        Summary.tree_type == "topic", Summary.scope_id == entity_id
                    )
                )
            )
            .scalars()
            .all()
        )


def _router(engine: AsyncEngine) -> TopicRouter:
    return TopicRouter(
        async_sessionmaker(engine, expire_on_commit=False),
        build_gateway(Settings(_env_file=None)),
        threshold=3.0,
    )


async def test_cold_entity_gets_hotness_but_no_topic_tree(engine: AsyncEngine) -> None:
    entity_id = await _seed_entity_with_mentions(engine, "ColdProject", [60, 90])
    await _router(engine).topic_route({"entity_id": entity_id})

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        entity = await session.get(Entity, entity_id)
    assert entity is not None and entity.hotness is not None
    assert entity.hotness < 3.0
    assert await _topic_nodes(engine, entity_id) == [], "cold topics must not materialize"


async def test_hot_entity_materializes_topic_tree_with_mentions(engine: AsyncEngine) -> None:
    entity_id = await _seed_entity_with_mentions(engine, "HotProject", [0, 0, 0, 1])
    await _router(engine).topic_route({"entity_id": entity_id})

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        entity = await session.get(Entity, entity_id)
    assert entity is not None and entity.hotness is not None and entity.hotness > 3.0

    nodes = await _topic_nodes(engine, entity_id)
    assert len(nodes) == 1, "hot topic materializes exactly one L1 node"
    assert len(nodes[0].child_ids["chunks"]) == 4

    # Re-routing refreshes the same node rather than duplicating it.
    await _router(engine).topic_route({"entity_id": entity_id})
    assert len(await _topic_nodes(engine, entity_id)) == 1


async def test_missing_entity_is_skipped(engine: AsyncEngine) -> None:
    await _router(engine).topic_route({"entity_id": "does-not-exist"})
