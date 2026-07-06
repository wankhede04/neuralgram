"""Unit tests for digest schedule timing (M3-3)."""

from datetime import UTC, datetime

from neuralgram.memory.digest import next_midnight_utc


def test_next_midnight_is_strictly_after_now() -> None:
    now = datetime(2026, 7, 6, 15, 30, tzinfo=UTC)
    assert next_midnight_utc(now) == datetime(2026, 7, 7, 0, 0, tzinfo=UTC)


def test_exactly_midnight_schedules_the_following_midnight() -> None:
    midnight = datetime(2026, 7, 6, 0, 0, tzinfo=UTC)
    assert next_midnight_utc(midnight) == datetime(2026, 7, 7, 0, 0, tzinfo=UTC)


def test_one_second_before_midnight() -> None:
    now = datetime(2026, 7, 6, 23, 59, 59, tzinfo=UTC)
    assert next_midnight_utc(now) == datetime(2026, 7, 7, 0, 0, tzinfo=UTC)
