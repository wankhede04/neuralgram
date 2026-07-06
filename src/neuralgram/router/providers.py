"""Real provider adapters (C4, M4-2): Anthropic and OpenAI.

Adapters are contract-tested against mock transports (standards §4); any
network/HTTP/parse failure raises `ProviderError` so the gateway's
failover can move to the next provider. Activating a real provider needs
its API key configured — that remains an external-cost human gate.
"""

from typing import Any

import httpx

from neuralgram.common.errors import ProviderError
from neuralgram.router.gateway import CompletionResult, Message, Usage

DEFAULT_TIMEOUT_SECONDS = 60.0


class AnthropicProvider:
    """Adapter for the Anthropic Messages API."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=DEFAULT_TIMEOUT_SECONDS,
            transport=transport,
        )

    async def complete(self, messages: list[Message], model_or_hint: str) -> CompletionResult:
        """POST /v1/messages; returns text + token usage."""
        payload = {
            "model": model_or_hint,
            "max_tokens": 4096,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        data = await self._post("/v1/messages", payload)
        try:
            return CompletionResult(
                text=data["content"][0]["text"],
                usage=Usage(
                    tokens_in=data["usage"]["input_tokens"],
                    tokens_out=data["usage"]["output_tokens"],
                ),
                provider=self.name,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"anthropic: unexpected response shape: {exc}") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Anthropic exposes no embeddings API; route `hint:embed` elsewhere."""
        raise ProviderError("anthropic provides no embeddings API")

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
            return dict(response.json())
        except httpx.HTTPError as exc:
            raise ProviderError(f"anthropic: {exc}") from exc

    async def close(self) -> None:
        """Release the HTTP connection pool."""
        await self._client.aclose()


class OpenAIProvider:
    """Adapter for the OpenAI Chat Completions and Embeddings APIs."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com",
        embedding_model: str = "text-embedding-3-small",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._embedding_model = embedding_model
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            timeout=DEFAULT_TIMEOUT_SECONDS,
            transport=transport,
        )

    async def complete(self, messages: list[Message], model_or_hint: str) -> CompletionResult:
        """POST /v1/chat/completions; returns text + token usage."""
        payload = {
            "model": model_or_hint,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        data = await self._post("/v1/chat/completions", payload)
        try:
            return CompletionResult(
                text=data["choices"][0]["message"]["content"],
                usage=Usage(
                    tokens_in=data["usage"]["prompt_tokens"],
                    tokens_out=data["usage"]["completion_tokens"],
                ),
                provider=self.name,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"openai: unexpected response shape: {exc}") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """POST /v1/embeddings; returns one vector per input, input order preserved."""
        data = await self._post("/v1/embeddings", {"model": self._embedding_model, "input": texts})
        try:
            items = sorted(data["data"], key=lambda item: item["index"])
            return [list(map(float, item["embedding"])) for item in items]
        except (KeyError, TypeError) as exc:
            raise ProviderError(f"openai: unexpected embeddings shape: {exc}") from exc

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
            return dict(response.json())
        except httpx.HTTPError as exc:
            raise ProviderError(f"openai: {exc}") from exc

    async def close(self) -> None:
        """Release the HTTP connection pool."""
        await self._client.aclose()
