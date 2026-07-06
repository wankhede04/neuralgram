"""Unit tests for prompt/response caching (M4-4 acceptance)."""

from neuralgram.common.config import Settings
from neuralgram.observability import metrics
from neuralgram.router.cache import InMemoryResponseCache
from neuralgram.router.gateway import (
    CompletionResult,
    Message,
    MockProvider,
    ModelGateway,
    cache_key,
)
from neuralgram.router.routing import RouteTable, mock_route_table


class CountingProvider(MockProvider):
    def __init__(self, embedding_dim: int = 16) -> None:
        super().__init__(embedding_dim)
        self.calls = 0

    async def complete(self, messages: list[Message], model_or_hint: str) -> CompletionResult:
        self.calls += 1
        return await super().complete(messages, model_or_hint)


def _gateway(provider: CountingProvider) -> ModelGateway:
    return ModelGateway(
        {"mock": provider},
        RouteTable(mock_route_table(), default_provider="mock"),
        cache=InMemoryResponseCache(),
    )


def _hits(hint: str) -> float:
    return metrics.registry.get_sample_value("neuralgram_cache_hits_total", {"hint": hint}) or 0.0


async def test_cache_hit_skips_provider_and_preserves_correctness() -> None:
    provider = CountingProvider()
    gateway = _gateway(provider)
    messages = [Message(role="user", content="what changed in the deploy?")]

    first = await gateway.complete(messages, "hint:fast")
    hits_before = _hits("fast")
    second = await gateway.complete(messages, "hint:fast")

    assert provider.calls == 1, "second call must be served from cache"
    assert second == first, "cached result must be byte-identical"
    assert _hits("fast") == hits_before + 1, "cache hit must be measured"


async def test_different_messages_and_models_miss() -> None:
    provider = CountingProvider()
    gateway = _gateway(provider)

    await gateway.complete([Message(role="user", content="alpha")], "hint:fast")
    await gateway.complete([Message(role="user", content="beta")], "hint:fast")
    await gateway.complete([Message(role="user", content="alpha")], "hint:summarize")
    assert provider.calls == 3


def test_cache_key_is_deterministic_and_route_sensitive() -> None:
    messages = [Message(role="user", content="hello")]
    assert cache_key("mock", "m1", messages) == cache_key("mock", "m1", messages)
    assert cache_key("mock", "m1", messages) != cache_key("mock", "m2", messages)
    assert cache_key("a", "m1", messages) != cache_key("b", "m1", messages)


async def test_settings_gateway_without_cache_always_calls_provider() -> None:
    provider = CountingProvider(embedding_dim=Settings(_env_file=None).embedding_dim)
    gateway = ModelGateway(
        {"mock": provider}, RouteTable(mock_route_table(), default_provider="mock")
    )
    messages = [Message(role="user", content="no cache configured")]
    await gateway.complete(messages, "hint:fast")
    await gateway.complete(messages, "hint:fast")
    assert provider.calls == 2
