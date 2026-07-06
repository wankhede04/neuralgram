"""Unit tests for ContentStore logic with a fake session (real-DB behavior is
covered in tests/integration/test_content_store.py)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import pytest

from neuralgram.ingestion.canonicalize import Provenance
from neuralgram.memory.chunker import ChunkDraft
from neuralgram.memory.store import ContentStore


def _draft(chunk_id: str, tenant_id: str = "tenant-a") -> ChunkDraft:
    return ChunkDraft(
        id=chunk_id,
        tenant_id=tenant_id,
        source_id="C042MEMORY",
        content_md=f"content {chunk_id}",
        token_count=2,
        provenance=Provenance(
            source_type="slack",
            source_id="C042MEMORY",
            external_id="1783296000.000100",
            author="U01ALICE",
            timestamp=datetime(2026, 7, 6, tzinfo=UTC),
        ),
        content_hash=chunk_id,
    )


class FakeSession:
    """Minimal async-session stand-in: every insert 'succeeds' for all rows."""

    def __init__(self, fail_on_commit: bool = False) -> None:
        self.fail_on_commit = fail_on_commit
        self.committed = False
        self.statements: list[Any] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def execute(self, statement: Any) -> Any:
        self.statements.append(statement)
        params = statement.compile().params
        ids = [value for key, value in params.items() if key.startswith("id")]
        return [(chunk_id,) for chunk_id in ids]

    async def commit(self) -> None:
        if self.fail_on_commit:
            raise RuntimeError("simulated commit failure")
        self.committed = True


def _store(tmp_path: Path, session: FakeSession) -> ContentStore:
    return ContentStore(lambda: session, tmp_path)  # type: ignore[arg-type]


def test_vault_file_layout(tmp_path: Path) -> None:
    store = _store(tmp_path, FakeSession())
    assert store.vault_file("tenant-a", "abc123") == tmp_path / "tenant-a" / "abc123.md"


async def test_empty_batch_is_a_noop(tmp_path: Path) -> None:
    session = FakeSession()
    result = await _store(tmp_path, session).persist([])
    assert (result.inserted, result.skipped) == (0, 0)
    assert session.statements == []


async def test_within_batch_duplicates_are_deduped(tmp_path: Path) -> None:
    session = FakeSession()
    result = await _store(tmp_path, session).persist([_draft("dup"), _draft("dup")])
    assert result.inserted == 1
    assert (tmp_path / "tenant-a" / "dup.md").is_file()


async def test_happy_path_writes_files_and_commits(tmp_path: Path) -> None:
    session = FakeSession()
    result = await _store(tmp_path, session).persist([_draft("c1"), _draft("c2")])
    assert result.inserted == 2
    assert session.committed
    assert (tmp_path / "tenant-a" / "c1.md").read_text(encoding="utf-8") == "content c1"


async def test_commit_failure_cleans_up_written_files(tmp_path: Path) -> None:
    session = FakeSession(fail_on_commit=True)
    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await _store(tmp_path, session).persist([_draft("c1"), _draft("c2")])
    assert not list(tmp_path.rglob("*.md")), "files from the failed call must be removed"
