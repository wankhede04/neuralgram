"""Unit tests for reciprocal-rank fusion in hybrid search (M2-5)."""

from typing import Any

import pytest

from neuralgram.memory.retrieval import ChunkRetrieval, RetrievedChunk


def _result(chunk_id: str, rank: float | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_id="C042MEMORY",
        content_md=f"content {chunk_id}",
        token_count=2,
        lifecycle="admitted",
        provenance={"source_type": "slack"},
        rank=rank,
    )


@pytest.fixture
def retrieval(monkeypatch: pytest.MonkeyPatch) -> ChunkRetrieval:
    retrieval = ChunkRetrieval("tenant-a")

    async def fake_keyword(session: Any, query: str, limit: int = 10) -> list[RetrievedChunk]:
        return [_result("kw-only"), _result("both")]

    async def fake_semantic(
        session: Any, vector: list[float], limit: int = 10
    ) -> list[RetrievedChunk]:
        return [_result("both"), _result("sem-only")]

    monkeypatch.setattr(retrieval, "search", fake_keyword)
    monkeypatch.setattr(retrieval, "semantic_search", fake_semantic)
    return retrieval


async def test_rrf_ranks_agreement_first(retrieval: ChunkRetrieval) -> None:
    fused = await retrieval.hybrid_search(None, "q", [0.0], limit=10)  # type: ignore[arg-type]
    ids = [r.chunk_id for r in fused]
    assert ids[0] == "both", "chunk found by both retrievers must rank first"
    assert set(ids) == {"both", "kw-only", "sem-only"}

    expected_both = 1 / (60 + 2) + 1 / (60 + 1)
    assert fused[0].rank == pytest.approx(expected_both)


async def test_rrf_respects_limit(retrieval: ChunkRetrieval) -> None:
    fused = await retrieval.hybrid_search(None, "q", [0.0], limit=1)  # type: ignore[arg-type]
    assert len(fused) == 1 and fused[0].chunk_id == "both"
