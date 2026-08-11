"""Per-IP, per-category daily request cap for the unauthenticated demo tenant."""

from datetime import UTC, datetime

import redis.asyncio as aioredis

from neuralgram.common.errors import NeuralgramError

_DAY_SECONDS = 86_400

_CATEGORY_LABELS = {
    "ingest": "ingest calls",
    "search": "semantic/hybrid search calls",
}


class DemoRateLimitExceededError(NeuralgramError):
    """A demo visitor's IP address exceeded its daily request cap for one category."""


class DemoIpRateLimiter:
    """Atomic per-IP, per-category daily counter backed by Redis (safe across concurrent workers).

    `category` distinguishes what kind of request this is (e.g. "ingest"
    vs "search") so each gets its own independent daily budget per IP --
    keyword search and summaries make no AI call and are never metered
    through this limiter at all (call sites simply don't call it for them).
    """

    def __init__(self, redis_url: str, daily_limit: int) -> None:
        self._client: aioredis.Redis = aioredis.from_url(redis_url)
        self._limit = daily_limit

    async def check_and_increment(self, ip: str, category: str) -> None:
        """Raise `DemoRateLimitExceededError` once `ip` exceeds `category`'s daily cap."""
        day = datetime.now(UTC).date().isoformat()
        key = f"demo-rate:{ip}:{day}:{category}"
        count = await self._client.incr(key)
        if count == 1:
            await self._client.expire(key, _DAY_SECONDS)
        if count > self._limit:
            label = _CATEGORY_LABELS.get(category, f"{category} calls")
            raise DemoRateLimitExceededError(
                f"The demo is limited to {self._limit} {label} per day per visitor. "
                "Sign up for your own tenant with no limits, or try again tomorrow."
            )

    async def close(self) -> None:
        """Release the Redis connection pool."""
        await self._client.aclose()
