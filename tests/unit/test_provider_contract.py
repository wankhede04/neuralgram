"""Contract tests every ModelProvider adapter must pass (M2-3 acceptance).

Currently only the mock provider exists; real adapters (M4-2, gated) must
be added to `PROVIDERS` and satisfy the same contract.
"""

import pytest

from neuralgram.router.gateway import Message, MockProvider, ModelProvider

PROVIDERS: list[ModelProvider] = [MockProvider(embedding_dim=16)]


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.name)
async def test_embed_contract(provider: ModelProvider) -> None:
    texts = ["alpha", "beta", "日本語 🎉"]
    vectors = await provider.embed(texts)

    assert len(vectors) == len(texts), "one vector per input text"
    dims = {len(v) for v in vectors}
    assert len(dims) == 1, "all vectors share one dimension"
    assert all(isinstance(x, float) for v in vectors for x in v)
    assert await provider.embed(texts) == vectors, "embedding must be deterministic"
    assert await provider.embed([]) == []


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.name)
async def test_complete_contract(provider: ModelProvider) -> None:
    result = await provider.complete([Message(role="user", content="ping")], "hint:embed")
    assert result.text
    assert result.provider == provider.name
    assert result.usage.tokens_in >= 1
    assert result.usage.tokens_out >= 1
