"""Integration: labeled fixture eval — semantic/hybrid beats keyword-only (M2-5 acceptance)."""

import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
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
from neuralgram.memory.retrieval import ChunkRetrieval
from neuralgram.memory.store import ContentStore
from neuralgram.router.gateway import ModelGateway, build_gateway

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL = json.loads((REPO_ROOT / "tests" / "fixtures" / "retrieval_eval.json").read_text())
TENANT = "tenant-eval"


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


@pytest.fixture(scope="module")
def label_by_chunk(async_url: str, tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Seed the eval docs and embed them; returns chunk_id -> doc label."""
    import asyncio

    mapping: dict[str, str] = {}

    async def _seed() -> None:
        engine = create_async_engine(async_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        store = ContentStore(factory, tmp_path_factory.mktemp("vault"))
        gateway = build_gateway(Settings(_env_file=None))
        for doc in EVAL["docs"]:
            canonical = CanonicalDoc(
                body_md=doc["text"],
                provenance=Provenance(
                    source_type="slack",
                    source_id="C042MEMORY",
                    external_id=doc["label"],
                    author="U01ALICE",
                    timestamp=datetime(2026, 7, 6, tzinfo=UTC),
                ),
                source_type="slack",
            )
            drafts = chunk(canonical, TENANT)
            assert len(drafts) == 1
            await store.persist(drafts)
            vector = (await gateway.embed([drafts[0].content_md]))[0]
            async with factory() as session:
                await persist_embeddings(session, {drafts[0].id: vector}, TENANT)
                await session.commit()
            mapping[drafts[0].id] = doc["label"]
        await engine.dispose()

    asyncio.run(_seed())
    return mapping


@pytest.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def _recall_at_1(
    session: AsyncSession,
    label_by_chunk: dict[str, str],
    gateway: ModelGateway,
    mode: str,
) -> float:
    retrieval = ChunkRetrieval(TENANT)
    hits = 0
    for item in EVAL["queries"]:
        query, relevant = item["query"], item["relevant"]
        if mode == "keyword":
            results = await retrieval.search(session, query, limit=3)
        elif mode == "semantic":
            vector = (await gateway.embed([query]))[0]
            results = await retrieval.semantic_search(session, vector, limit=3)
        else:
            vector = (await gateway.embed([query]))[0]
            results = await retrieval.hybrid_search(session, query, vector, limit=3)
        if results and label_by_chunk.get(results[0].chunk_id) == relevant:
            hits += 1
    return hits / len(EVAL["queries"])


async def test_semantic_and_hybrid_beat_keyword_on_labeled_eval(
    session: AsyncSession, label_by_chunk: dict[str, str]
) -> None:
    gateway = build_gateway(Settings(_env_file=None))

    keyword = await _recall_at_1(session, label_by_chunk, gateway, "keyword")
    semantic = await _recall_at_1(session, label_by_chunk, gateway, "semantic")
    hybrid = await _recall_at_1(session, label_by_chunk, gateway, "hybrid")

    assert semantic > keyword, f"semantic {semantic} must beat keyword {keyword}"
    assert hybrid > keyword, f"hybrid {hybrid} must beat keyword {keyword}"
    assert hybrid >= semantic, "fusion must not lose to its best component here"
