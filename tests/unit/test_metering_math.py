"""Unit tests for cost math (M4-3)."""

from decimal import Decimal

from neuralgram.router.metering import PRICE_TABLE, call_cost_usd


def test_cost_uses_price_table() -> None:
    cost = call_cost_usd("mock", "mock-fast", tokens_in=1_000_000, tokens_out=1_000_000)
    assert cost == Decimal("6.00")  # $1 in + $5 out per 1M


def test_cost_scales_linearly_and_supports_zero() -> None:
    assert call_cost_usd("mock", "mock-fast", 500_000, 0) == Decimal("0.50")
    assert call_cost_usd("mock", "mock-embed", 1_000_000, 0) == Decimal("0.10")
    assert call_cost_usd("mock", "mock-fast", 0, 0) == Decimal("0")


def test_unknown_model_gets_default_price() -> None:
    assert ("mock", "mystery-model") not in PRICE_TABLE
    cost = call_cost_usd("mock", "mystery-model", 1_000_000, 0)
    assert cost == Decimal("3.00")
