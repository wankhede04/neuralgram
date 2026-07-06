"""C4 prompt/response cache implementations (M4-4).

The `ResponseCache` protocol and cache key live in `router.gateway`.
Backend failures degrade to a miss (the model call still happens), so
caching can never break correctness or availability.
"""

import redis.asyncio as aioredis

from neuralgram.observability.logging import get_logger
from neuralgram.router.gateway import CompletionResult

logger = get_logger(__name__)


class InMemoryResponseCache:
    """Process-local cache for dev and unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> CompletionResult | None:
        raw = self._store.get(key)
        return CompletionResult.model_validate_json(raw) if raw else None

    async def set(self, key: str, value: CompletionResult) -> None:
        self._store[key] = value.model_dump_json()


class RedisResponseCache:
    """Redis-backed cache with TTL; errors degrade to misses."""

    def __init__(self, redis_url: str, ttl_seconds: int = 3600) -> None:
        self._client: aioredis.Redis = aioredis.from_url(redis_url)
        self._ttl = ttl_seconds

    async def get(self, key: str) -> CompletionResult | None:
        try:
            raw = await self._client.get(key)
        except Exception:
            logger.warning("cache.get_failed", key=key)
            return None
        return CompletionResult.model_validate_json(raw) if raw else None

    async def set(self, key: str, value: CompletionResult) -> None:
        try:
            await self._client.set(key, value.model_dump_json(), ex=self._ttl)
        except Exception:
            logger.warning("cache.set_failed", key=key)

    async def close(self) -> None:
        """Release the Redis connection pool."""
        await self._client.aclose()
