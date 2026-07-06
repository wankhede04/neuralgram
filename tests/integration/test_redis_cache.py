"""Integration: Redis-backed response cache over real Redis (M4-4 acceptance)."""

from collections.abc import AsyncIterator

import pytest
from testcontainers.redis import RedisContainer

from neuralgram.common.config import Settings
from neuralgram.router.cache import RedisResponseCache
from neuralgram.router.gateway import Message, build_gateway


@pytest.fixture
async def cache() -> AsyncIterator[RedisResponseCache]:
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        cache = RedisResponseCache(f"redis://{host}:{port}/0", ttl_seconds=60)
        try:
            yield cache
        finally:
            await cache.close()


async def test_gateway_serves_second_call_from_redis(cache: RedisResponseCache) -> None:
    gateway = build_gateway(Settings(_env_file=None), cache=cache)
    messages = [Message(role="user", content="cache me over real redis")]

    first = await gateway.complete(messages, "hint:fast")
    second = await gateway.complete(messages, "hint:fast")
    assert second == first


async def test_backend_failure_degrades_to_miss() -> None:
    broken = RedisResponseCache("redis://127.0.0.1:1/0", ttl_seconds=60)  # nothing listens
    gateway = build_gateway(Settings(_env_file=None), cache=broken)
    messages = [Message(role="user", content="redis is down")]

    result = await gateway.complete(messages, "hint:fast")
    assert result.text, "call must succeed even with a dead cache backend"
    await broken.close()
