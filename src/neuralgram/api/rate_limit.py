"""Per-IP daily request cap for the unauthenticated demo tenant."""

from datetime import UTC, datetime

import redis.asyncio as aioredis

from neuralgram.common.errors import NeuralgramError

_DAY_SECONDS = 86_400


class DemoRateLimitExceededError(NeuralgramError):
    """A demo visitor's IP address exceeded its daily request cap."""


class DemoIpRateLimiter:
    """Atomic per-IP daily counter backed by Redis (safe across concurrent workers)."""

    def __init__(self, redis_url: str, daily_limit: int) -> None:
        self._client: aioredis.Redis = aioredis.from_url(redis_url)
        self._limit = daily_limit

    async def check_and_increment(self, ip: str) -> None:
        """Raise `DemoRateLimitExceededError` once `ip` exceeds the daily cap."""
        day = datetime.now(UTC).date().isoformat()
        key = f"demo-rate:{ip}:{day}"
        count = await self._client.incr(key)
        if count == 1:
            await self._client.expire(key, _DAY_SECONDS)
        if count > self._limit:
            raise DemoRateLimitExceededError(
                f"The demo is limited to {self._limit} requests per day per visitor. "
                "Sign up for your own tenant with no limits, or try again tomorrow."
            )

    async def close(self) -> None:
        """Release the Redis connection pool."""
        await self._client.aclose()
