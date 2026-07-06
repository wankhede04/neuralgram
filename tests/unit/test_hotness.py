"""Unit tests for hotness math (M3-2 acceptance)."""

from datetime import UTC, datetime, timedelta

import pytest

from neuralgram.memory.hotness import hotness

NOW = datetime(2026, 7, 6, tzinfo=UTC)
HALF_LIFE = timedelta(days=7)


def test_fresh_mention_counts_one_and_empty_counts_zero() -> None:
    assert hotness([NOW], NOW, HALF_LIFE) == pytest.approx(1.0)
    assert hotness([], NOW, HALF_LIFE) == 0.0


def test_mention_aged_one_half_life_counts_half() -> None:
    assert hotness([NOW - HALF_LIFE], NOW, HALF_LIFE) == pytest.approx(0.5)
    assert hotness([NOW - 2 * HALF_LIFE], NOW, HALF_LIFE) == pytest.approx(0.25)


def test_hotness_is_sum_over_mentions() -> None:
    mentions = [NOW, NOW - HALF_LIFE, NOW - 2 * HALF_LIFE]
    assert hotness(mentions, NOW, HALF_LIFE) == pytest.approx(1.0 + 0.5 + 0.25)


def test_more_recent_mentions_score_higher() -> None:
    recent = [NOW - timedelta(days=1)] * 3
    old = [NOW - timedelta(days=30)] * 3
    assert hotness(recent, NOW, HALF_LIFE) > hotness(old, NOW, HALF_LIFE)


def test_future_mentions_clamp_to_age_zero() -> None:
    assert hotness([NOW + timedelta(days=5)], NOW, HALF_LIFE) == pytest.approx(1.0)


def test_invalid_half_life_rejected() -> None:
    with pytest.raises(ValueError, match="half_life"):
        hotness([NOW], NOW, timedelta(0))
