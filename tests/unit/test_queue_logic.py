"""Unit tests for JobQueue branch logic with a scripted fake session
(real SKIP LOCKED/lease behavior is covered in tests/integration/test_job_queue.py)."""

from typing import Any, Self

import pytest

from neuralgram.memory.queue import JobQueue


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value

    def one(self) -> Any:
        return self._value


class FakeSession:
    """Returns scripted results for successive execute() calls."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.executed: list[Any] = []
        self.committed = 0
        self.rolled_back = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def execute(self, statement: Any) -> _Result:
        self.executed.append(statement)
        return _Result(self._script.pop(0))

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


def _queue(session: FakeSession, max_retries: int = 3) -> JobQueue:
    return JobQueue(lambda: session, max_retries=max_retries)  # type: ignore[arg-type]


async def test_enqueue_returns_id_or_none_on_dedupe() -> None:
    session = FakeSession(script=["job-1"])
    assert await _queue(session).enqueue("k", {}, "dk") == "job-1"
    assert session.committed == 1

    deduped = FakeSession(script=[None])
    assert await _queue(deduped).enqueue("k", {}, "dk") is None


async def test_claim_empty_queue_rolls_back_and_returns_none() -> None:
    session = FakeSession(script=[None])
    assert await _queue(session).claim("w1") is None
    assert session.rolled_back == 1
    assert session.committed == 0


async def test_claim_leases_the_selected_job() -> None:
    session = FakeSession(script=["job-1", ("job-1", "extract_chunk", {"c": 1}, 0)])
    claimed = await _queue(session).claim("w1", lease_seconds=30)
    assert claimed is not None
    assert (claimed.id, claimed.kind, claimed.payload, claimed.retry_count) == (
        "job-1",
        "extract_chunk",
        {"c": 1},
        0,
    )
    assert session.committed == 1


@pytest.mark.parametrize(("retry_count", "expected"), [(0, "queued"), (1, "queued"), (2, "failed")])
async def test_fail_requeues_until_retries_exhausted(retry_count: int, expected: str) -> None:
    session = FakeSession(script=[retry_count, None])
    assert await _queue(session, max_retries=3).fail("job-1") == expected


async def test_ack_commits() -> None:
    session = FakeSession(script=[None])
    await _queue(session).ack("job-1")
    assert session.committed == 1
