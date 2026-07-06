"""Unit tests for the mock model gateway (P0-4 acceptance)."""

import pytest

from neuralgram.common.config import Settings
from neuralgram.router.gateway import Message, build_gateway


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


async def test_mock_complete_is_deterministic() -> None:
    gateway = build_gateway(_settings())
    messages = [Message(role="user", content="hello neuralgram")]
    first = await gateway.complete(messages, "hint:fast")
    second = await gateway.complete(messages, "hint:fast")
    assert first == second
    assert first.provider == "mock"
    assert first.usage.tokens_in == 2
    assert first.text.startswith("[mock:hint:fast:")


async def test_mock_complete_varies_with_input() -> None:
    gateway = build_gateway(_settings())
    a = await gateway.complete([Message(role="user", content="alpha")], "hint:fast")
    b = await gateway.complete([Message(role="user", content="beta")], "hint:fast")
    c = await gateway.complete([Message(role="user", content="alpha")], "hint:reasoning")
    assert a.text != b.text
    assert a.text != c.text


async def test_mock_embed_is_deterministic_and_dimensioned() -> None:
    gateway = build_gateway(_settings(embedding_dim=16))
    first = await gateway.embed(["alpha", "beta"])
    second = await gateway.embed(["alpha", "beta"])
    assert first == second
    assert len(first) == 2
    assert all(len(vector) == 16 for vector in first)
    assert first[0] != first[1]
    assert all(-1.0 <= value < 1.0 for vector in first for value in vector)


async def test_real_providers_are_gated() -> None:
    with pytest.raises(RuntimeError, match="human gate"):
        build_gateway(_settings(mock_providers=False))
