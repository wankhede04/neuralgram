"""Unit tests for hint routing (M4-1 acceptance): every hint + fallthrough + remap."""

import pytest

from neuralgram.common.config import Settings
from neuralgram.common.errors import RoutingError
from neuralgram.router.gateway import Message, build_gateway
from neuralgram.router.routing import HINTS, RouteTable, mock_route_table


@pytest.mark.parametrize("hint", HINTS)
def test_every_hint_resolves_through_the_table(hint: str) -> None:
    table = RouteTable(mock_route_table(), default_provider="mock")
    resolution = table.resolve(f"hint:{hint}")
    assert resolution.provider == "mock"
    assert resolution.model == f"mock-{hint}"
    assert resolution.hint == hint


def test_concrete_model_name_falls_through_to_default_provider() -> None:
    table = RouteTable(mock_route_table(), default_provider="mock")
    resolution = table.resolve("claude-opus-4-7")
    assert resolution.provider == "mock"
    assert resolution.model == "claude-opus-4-7"
    assert resolution.hint is None


def test_unknown_hint_and_unrouted_hint_raise() -> None:
    table = RouteTable(mock_route_table(), default_provider="mock")
    with pytest.raises(RoutingError, match="unknown hint"):
        table.resolve("hint:telepathy")

    sparse = RouteTable({"fast": ("mock", "mock-fast")}, default_provider="mock")
    with pytest.raises(RoutingError, match="no route configured"):
        sparse.resolve("hint:reasoning")


def test_route_table_rejects_unknown_hints_at_build_and_remap() -> None:
    with pytest.raises(RoutingError, match="unknown hints"):
        RouteTable({"telepathy": ("mock", "m")}, default_provider="mock")
    table = RouteTable(mock_route_table(), default_provider="mock")
    with pytest.raises(RoutingError, match="cannot remap"):
        table.remap("telepathy", "mock", "m")


def test_runtime_remap_changes_resolution() -> None:
    table = RouteTable(mock_route_table(), default_provider="mock")
    table.remap("reasoning", "anthropic", "claude-opus-4-7")
    resolution = table.resolve("hint:reasoning")
    assert (resolution.provider, resolution.model) == ("anthropic", "claude-opus-4-7")
    assert table.snapshot()["fast"] == ("mock", "mock-fast"), "other hints untouched"


async def test_gateway_dispatches_via_route_table() -> None:
    gateway = build_gateway(Settings(_env_file=None))
    result = await gateway.complete([Message(role="user", content="ping")], "hint:fast")
    assert result.provider == "mock"
    assert "[mock:mock-fast:" in result.text, "provider must receive the resolved model"


async def test_gateway_unknown_provider_after_remap_raises() -> None:
    gateway = build_gateway(Settings(_env_file=None))
    gateway.route_table.remap("fast", "anthropic", "claude-haiku-4-5")
    with pytest.raises(RoutingError, match="no provider adapter"):
        await gateway.complete([Message(role="user", content="ping")], "hint:fast")
