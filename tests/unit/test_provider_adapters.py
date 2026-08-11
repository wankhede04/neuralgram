"""Contract tests for real provider adapters against mock transports (M4-2).

Asserts request shape (URL, auth headers, body) and response parsing per
provider, per standards §4 — no real API keys, no network, no spend.
"""

import json
from typing import Any

import httpx
import pytest

from neuralgram.common.errors import ProviderError
from neuralgram.router.gateway import Message
from neuralgram.router.providers import AnthropicProvider, JinaProvider, OpenAIProvider

MESSAGES = [Message(role="user", content="ping")]


def _transport(
    handler_response: dict[str, Any], status_code: int = 200
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code, json=handler_response)

    return httpx.MockTransport(handler), seen


async def test_anthropic_request_shape_and_parsing() -> None:
    transport, seen = _transport(
        {
            "content": [{"type": "text", "text": "pong"}],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }
    )
    provider = AnthropicProvider("test-key", transport=transport)  # pragma: allowlist secret

    result = await provider.complete(MESSAGES, "claude-opus-4-7")

    request = seen[0]
    assert request.url.path == "/v1/messages"
    assert request.headers["x-api-key"] == "test-key"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert body["model"] == "claude-opus-4-7"
    assert body["messages"] == [{"role": "user", "content": "ping"}]

    assert result.text == "pong"
    assert (result.usage.tokens_in, result.usage.tokens_out) == (11, 7)
    assert result.provider == "anthropic"
    await provider.close()


async def test_openai_request_shape_and_parsing() -> None:
    transport, seen = _transport(
        {
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 5},
        }
    )
    provider = OpenAIProvider("test-key", transport=transport)  # pragma: allowlist secret

    result = await provider.complete(MESSAGES, "gpt-4o")

    request = seen[0]
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "gpt-4o"

    assert result.text == "pong"
    assert (result.usage.tokens_in, result.usage.tokens_out) == (9, 5)
    assert result.provider == "openai"
    await provider.close()


async def test_openai_embeddings_preserve_input_order() -> None:
    transport, seen = _transport(
        {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }
    )
    provider = OpenAIProvider("test-key", transport=transport)  # pragma: allowlist secret

    vectors = await provider.embed(["first", "second"])

    assert seen[0].url.path == "/v1/embeddings"
    assert json.loads(seen[0].content)["input"] == ["first", "second"]
    assert vectors == [[0.1, 0.2], [0.3, 0.4]], "results must be re-sorted by index"
    await provider.close()


async def test_jina_request_shape_and_parsing() -> None:
    transport, seen = _transport(
        {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }
    )
    provider = JinaProvider(
        "test-key", dimensions=384, transport=transport
    )  # pragma: allowlist secret

    vectors = await provider.embed(["first", "second"])

    request = seen[0]
    assert request.url.path == "/v1/embeddings"
    assert request.headers["authorization"] == "Bearer test-key"
    # Cloudflare fronts api.jina.ai and 403s the default httpx/urllib UA.
    assert "python" not in request.headers["user-agent"].lower()
    body = json.loads(request.content)
    assert body["model"] == "jina-embeddings-v3"
    assert body["dimensions"] == 384
    assert body["input"] == ["first", "second"]

    assert vectors == [[0.1, 0.2], [0.3, 0.4]], "results must be re-sorted by index"
    await provider.close()


async def test_jina_has_no_completions() -> None:
    transport, _ = _transport({})
    provider = JinaProvider("test-key", transport=transport)  # pragma: allowlist secret
    with pytest.raises(ProviderError, match="no completions"):
        await provider.complete(MESSAGES, "n/a")
    await provider.close()


async def test_anthropic_has_no_embeddings() -> None:
    transport, _ = _transport({})
    provider = AnthropicProvider("test-key", transport=transport)  # pragma: allowlist secret
    with pytest.raises(ProviderError, match="no embeddings"):
        await provider.embed(["text"])
    await provider.close()


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_http_errors_become_provider_errors(status: int) -> None:
    transport, _ = _transport({"error": "boom"}, status_code=status)
    anthropic = AnthropicProvider("test-key", transport=transport)  # pragma: allowlist secret
    openai = OpenAIProvider("test-key", transport=transport)  # pragma: allowlist secret
    jina = JinaProvider("test-key", transport=transport)  # pragma: allowlist secret

    with pytest.raises(ProviderError, match="anthropic"):
        await anthropic.complete(MESSAGES, "claude-opus-4-7")
    with pytest.raises(ProviderError, match="openai"):
        await openai.complete(MESSAGES, "gpt-4o")
    with pytest.raises(ProviderError, match="jina"):
        await jina.embed(["text"])
    await anthropic.close()
    await openai.close()
    await jina.close()


async def test_malformed_response_becomes_provider_error() -> None:
    transport, _ = _transport({"unexpected": "shape"})
    provider = AnthropicProvider("test-key", transport=transport)  # pragma: allowlist secret
    with pytest.raises(ProviderError, match="unexpected response shape"):
        await provider.complete(MESSAGES, "claude-opus-4-7")
    await provider.close()
