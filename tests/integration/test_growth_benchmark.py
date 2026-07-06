"""Integration benchmark: cost stays bounded as data grows (M3-5 acceptance).

Two properties, asserted with generous CI margins and documented with the
measured numbers in DECISIONS.md (ADR-0011):
  1. Amortized summarize-call input tokens per ingested chunk stay ~flat
     as the corpus doubles (seals are bounded by buffer_size).
  2. Hybrid retrieval latency grows sub-linearly with corpus size.
"""

import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from neuralgram.common.config import Settings
from neuralgram.memory.embeddings import persist_embeddings
from neuralgram.memory.retrieval import ChunkRetrieval
from neuralgram.memory.trees import SourceTree
from neuralgram.router.gateway import CompletionResult, Message, ModelGateway, build_gateway
from neuralgram.storage.models import Chunk

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = "C042MEMORY"
SIZES = [64, 128, 256]


class CountingGateway(ModelGateway):
    """Wraps the mock gateway, accumulating summarize-call input tokens."""

    def __init__(self, inner: ModelGateway) -> None:
        self._inner = inner
        self.summarize_tokens_in = 0

    async def complete(
        self, messages: list[Message], model_or_hint: str, tenant_id: str | None = None
    ) -> CompletionResult:
        result = await self._inner.complete(messages, model_or_hint, tenant_id)
        if model_or_hint == "hint:summarize":
            self.summarize_tokens_in += result.usage.tokens_in
        return result

    async def embed(self, texts: list[str], tenant_id: str | None = None) -> list[list[float]]:
        return await self._inner.embed(texts, tenant_id)


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


async def _grow_tenant(async_url: str, tenant: str, count: int) -> tuple[float, float]:
    """Seed `count` chunks through the tree; return (tokens/chunk, search seconds)."""
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    gateway = CountingGateway(build_gateway(Settings(_env_file=None)))
    tree = SourceTree(factory, gateway, buffer_size=8, cascade_size=4)

    now = datetime.now(tz=UTC)
    for i in range(count):
        chunk_id = uuid.uuid4().hex
        content = (
            f"update {i}: service checkpoint {chunk_id[:6]} deploy pipeline review "
            f"latency metrics rollout batch {i % 7}"
        )
        async with factory() as session:
            session.add(
                Chunk(
                    id=chunk_id,
                    tenant_id=tenant,
                    source_id=SOURCE,
                    content_md=content,
                    token_count=20,
                    provenance={"source_type": "slack"},
                    lifecycle="admitted",
                    content_hash=chunk_id,
                    created_at=now,
                )
            )
            await session.commit()
            vector = (await gateway.embed([content]))[0]
            await persist_embeddings(session, {chunk_id: vector})
            await session.commit()
        await tree.append_buffer({"chunk_id": chunk_id})

    retrieval = ChunkRetrieval(tenant)
    query = "deploy pipeline latency review"
    query_vector = (await gateway.embed([query]))[0]
    async with factory() as session:
        start = time.perf_counter()
        for _ in range(5):
            await retrieval.hybrid_search(session, query, query_vector, limit=10)
        elapsed = (time.perf_counter() - start) / 5

    await engine.dispose()
    return gateway.summarize_tokens_in / count, elapsed


async def test_growth_cost_is_bounded(async_url: str) -> None:
    tokens_per_chunk: list[float] = []
    latencies: list[float] = []
    for size in SIZES:
        per_chunk, latency = await _grow_tenant(async_url, f"tenant-bench-{size}", size)
        tokens_per_chunk.append(per_chunk)
        latencies.append(latency)

    print(f"\nBENCHMARK sizes={SIZES}")
    print(f"BENCHMARK summarize tokens/chunk={[round(t, 2) for t in tokens_per_chunk]}")
    print(f"BENCHMARK hybrid search seconds={[round(latency, 4) for latency in latencies]}")

    # Amortized summarization cost must not grow with corpus size (allow 50% jitter).
    assert tokens_per_chunk[-1] <= tokens_per_chunk[0] * 1.5, (
        f"summarize cost/chunk grew: {tokens_per_chunk}"
    )
    # Retrieval latency must grow sub-linearly: 4x data << 4x latency (generous 3x cap).
    assert latencies[-1] <= max(latencies[0], 0.005) * 3, f"retrieval latency grew: {latencies}"
