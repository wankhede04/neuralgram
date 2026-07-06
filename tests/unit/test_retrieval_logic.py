"""Unit tests for retrieval result mapping with a fake session
(real Postgres behavior covered in tests/integration/test_retrieval.py)."""

from typing import Any

from neuralgram.memory.retrieval import ChunkRetrieval
from neuralgram.storage.models import Chunk


def _chunk(chunk_id: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        tenant_id="tenant-a",
        source_id="C042MEMORY",
        content_md=f"content {chunk_id}",
        token_count=2,
        provenance={"source_type": "slack", "author": "U01ALICE"},
        lifecycle="admitted",
        content_hash=chunk_id,
    )


class FakeSession:
    def __init__(self, rows: list[Any], scalar: Any = None) -> None:
        self._rows = rows
        self._scalar = scalar

    async def execute(self, statement: Any) -> Any:
        rows = self._rows
        scalar = self._scalar

        class _Result:
            def __iter__(self) -> Any:
                return iter(rows)

            def scalar_one_or_none(self) -> Any:
                return scalar

        return _Result()


async def test_search_maps_rows_to_results_with_rank() -> None:
    session = FakeSession(rows=[(_chunk("c1"), 0.9), (_chunk("c2"), 0.5)])
    results = await ChunkRetrieval("tenant-a").search(session, "query")  # type: ignore[arg-type]
    assert [r.chunk_id for r in results] == ["c1", "c2"]
    assert results[0].rank == 0.9
    assert results[0].provenance["author"] == "U01ALICE"


async def test_semantic_search_maps_rows_to_results() -> None:
    session = FakeSession(rows=[(_chunk("c3"), 0.7)])
    results = await ChunkRetrieval("tenant-a").semantic_search(session, [0.0])  # type: ignore[arg-type]
    assert [r.chunk_id for r in results] == ["c3"]
    assert results[0].rank == 0.7


async def test_fetch_maps_row_and_none() -> None:
    found = await ChunkRetrieval("tenant-a").fetch(
        FakeSession(rows=[], scalar=_chunk("c4")),  # type: ignore[arg-type]
        "c4",
    )
    assert found is not None and found.chunk_id == "c4" and found.rank is None

    missing = await ChunkRetrieval("tenant-a").fetch(
        FakeSession(rows=[], scalar=None),  # type: ignore[arg-type]
        "nope",
    )
    assert missing is None
