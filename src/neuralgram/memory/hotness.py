"""Hotness math (C2.4): decayed mention frequency, pure and unit-testable.

`hotness = sum(mentions * recency_decay)` where each mention contributes
`0.5 ** (age / half_life)` — a mention aged exactly one half-life counts
as 0.5, a fresh mention as 1.0.
"""

from datetime import datetime, timedelta

DEFAULT_HALF_LIFE = timedelta(days=7)


def hotness(
    mention_times: list[datetime],
    now: datetime,
    half_life: timedelta = DEFAULT_HALF_LIFE,
) -> float:
    """Return the decayed mention score for `mention_times` as of `now`.

    Future-dated mentions are clamped to age zero. Empty input scores 0.0.
    """
    if half_life <= timedelta(0):
        raise ValueError("half_life must be positive")
    total = 0.0
    for ts in mention_times:
        age = max((now - ts).total_seconds(), 0.0)
        total += 0.5 ** (age / half_life.total_seconds())
    return total
