"""Failover tests (M4-2 acceptance): primary down -> secondary serves."""

import pytest

from neuralgram.common.errors import ProviderError
from neuralgram.router.gateway import CompletionResult, Message, ModelGateway, Usage
from neuralgram.router.health import ProviderHealth
from neuralgram.router.routing import RouteTable, mock_route_table

MESSAGES = [Message(role="user", content="ping")]


class FlakyProvider:
    """Fails the first `fail_first` calls, then succeeds (or always fails)."""

    def __init__(self, name: str, fail_first: int = 0, always_fail: bool = False) -> None:
        self.name = name
        self._fail_first = fail_first
        self._always_fail = always_fail
        self.calls = 0

    async def complete(self, messages: list[Message], model_or_hint: str) -> CompletionResult:
        self.calls += 1
        if self._always_fail or self.calls <= self._fail_first:
            raise ProviderError(f"{self.name} is down")
        return CompletionResult(
            text=f"served-by-{self.name}",
            usage=Usage(tokens_in=1, tokens_out=1),
            provider=self.name,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]


async def _noop_sleep(_: float) -> None:
    return None


def _gateway(
    primary: FlakyProvider, secondary: FlakyProvider, health: ProviderHealth | None = None
) -> ModelGateway:
    table = RouteTable(
        {"fast": ("primary", "model-a")},
        default_provider="primary",
        fallbacks={"fast": [("secondary", "model-b")]},
    )
    return ModelGateway(
        {"primary": primary, "secondary": secondary},
        table,
        health=health or ProviderHealth(failure_threshold=3),
        retry_attempts=2,
        sleep=_noop_sleep,
    )


async def test_primary_down_secondary_serves() -> None:
    primary = FlakyProvider("primary", always_fail=True)
    secondary = FlakyProvider("secondary")
    result = await _gateway(primary, secondary).complete(MESSAGES, "hint:fast")

    assert result.text == "served-by-secondary"
    assert primary.calls == 2, "primary retried before failover"
    assert secondary.calls == 1


async def test_transient_primary_failure_recovers_via_retry() -> None:
    primary = FlakyProvider("primary", fail_first=1)
    secondary = FlakyProvider("secondary")
    result = await _gateway(primary, secondary).complete(MESSAGES, "hint:fast")

    assert result.text == "served-by-primary", "retry on the same provider comes first"
    assert secondary.calls == 0


async def test_tripped_breaker_skips_primary_without_calls() -> None:
    primary = FlakyProvider("primary", always_fail=True)
    secondary = FlakyProvider("secondary")
    health = ProviderHealth(failure_threshold=2, cooldown_seconds=3600)
    gateway = _gateway(primary, secondary, health=health)

    await gateway.complete(MESSAGES, "hint:fast")  # trips the breaker (2 failures)
    calls_after_trip = primary.calls
    await gateway.complete(MESSAGES, "hint:fast")

    assert primary.calls == calls_after_trip, "tripped provider must be skipped entirely"


async def test_cooldown_expiry_readmits_the_provider() -> None:
    now = {"t": 0.0}
    health = ProviderHealth(failure_threshold=1, cooldown_seconds=10, clock=lambda: now["t"])
    health.record_failure("primary")
    assert not health.is_available("primary")
    now["t"] = 11.0
    assert health.is_available("primary")


async def test_all_providers_down_raises() -> None:
    primary = FlakyProvider("primary", always_fail=True)
    secondary = FlakyProvider("secondary", always_fail=True)
    with pytest.raises(ProviderError, match="all providers exhausted"):
        await _gateway(primary, secondary).complete(MESSAGES, "hint:fast")


async def test_mock_route_table_has_no_fallbacks() -> None:
    table = RouteTable(mock_route_table(), default_provider="mock")
    assert len(table.candidates("hint:fast")) == 1
    assert len(table.candidates("concrete-model")) == 1
