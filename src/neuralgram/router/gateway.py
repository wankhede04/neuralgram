"""Model gateway (C4): the single integration point for all model access.

Mock provider is the default. Real adapters (Anthropic, OpenAI) live in
`router/providers.py`; `build_gateway` wires them in when MOCK_PROVIDERS=false.
"""

import asyncio
import hashlib
import math
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from neuralgram.common.config import Settings
from neuralgram.common.errors import ProviderError, RoutingError
from neuralgram.observability import metrics
from neuralgram.router.health import ProviderHealth
from neuralgram.router.routing import HINTS, Resolution, RouteTable, mock_route_table

if TYPE_CHECKING:
    from neuralgram.router.metering import UsageMeter


class Message(BaseModel):
    """A single chat message sent to `complete`."""

    role: str
    content: str


class Usage(BaseModel):
    """Token accounting for one model call."""

    tokens_in: int
    tokens_out: int


class CompletionResult(BaseModel):
    """Result of a `complete` call: text plus usage and serving provider."""

    text: str
    usage: Usage
    provider: str


class ModelProvider(Protocol):
    """Interface every provider adapter (mock or real) must satisfy."""

    name: str

    async def complete(self, messages: list[Message], model_or_hint: str) -> CompletionResult:
        """Generate a completion for `messages` routed by `model_or_hint`."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed each text into a fixed-dimension vector."""
        ...


class ResponseCache(Protocol):
    """Interface for prompt/response caches over `complete` (M4-4)."""

    async def get(self, key: str) -> CompletionResult | None:
        """Return the cached completion for `key`, or None."""
        ...

    async def set(self, key: str, value: CompletionResult) -> None:
        """Store `value` under `key`."""
        ...


def cache_key(provider: str, model: str, messages: list[Message]) -> str:
    """Deterministic cache key over the resolved route and full message list."""
    joined = "\x1e".join(f"{m.role}\x1f{m.content}" for m in messages)
    return "nc:" + hashlib.sha256(f"{provider}|{model}|{joined}".encode()).hexdigest()


def _bow_embedding(text: str, dim: int) -> list[float]:
    """Deterministic feature-hashed bag-of-words embedding, L2-normalized.

    Texts sharing vocabulary land near each other in cosine space, so
    similarity search behaves meaningfully without any external model
    (ADR-0009).
    """
    vector = [0.0] * dim
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = sum(x * x for x in vector) ** 0.5
    if norm == 0.0:
        return vector
    return [x / norm for x in vector]


class MockProvider:
    """Deterministic, key-free provider for dev/CI (`MOCK_PROVIDERS=true`).

    Same input always yields the same output, so tests can assert on
    structure and stability without nondeterministic model output.
    """

    name = "mock"

    def __init__(self, embedding_dim: int) -> None:
        self._embedding_dim = embedding_dim

    async def complete(self, messages: list[Message], model_or_hint: str) -> CompletionResult:
        """Return a deterministic pseudo-completion derived from the input hash."""
        joined = "\n".join(f"{m.role}:{m.content}" for m in messages)
        fingerprint = hashlib.sha256(f"{model_or_hint}|{joined}".encode()).hexdigest()[:16]
        text = f"[mock:{model_or_hint}:{fingerprint}]"
        tokens_in = sum(len(m.content.split()) for m in messages)
        return CompletionResult(
            text=text,
            usage=Usage(tokens_in=tokens_in, tokens_out=len(text.split())),
            provider=self.name,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one deterministic bag-of-words vector per input text."""
        return [_bow_embedding(text, self._embedding_dim) for text in texts]


class ModelGateway:
    """Routes `complete`/`embed` through the hint table to provider adapters (C4).

    When a `UsageMeter` is attached and `tenant_id` is provided, every call
    is pre-checked against the tenant's hard spend cap and recorded after.
    """

    def __init__(
        self,
        providers: dict[str, ModelProvider],
        route_table: RouteTable,
        meter: "UsageMeter | None" = None,
        cache: ResponseCache | None = None,
        health: ProviderHealth | None = None,
        retry_attempts: int = 2,
        backoff_seconds: float = 0.2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._providers = providers
        self._route_table = route_table
        self._meter = meter
        self._cache = cache
        self._health = health or ProviderHealth()
        self._retry_attempts = retry_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    @property
    def route_table(self) -> RouteTable:
        """The live route table (remappable at runtime)."""
        return self._route_table

    def _provider_for(self, name: str) -> ModelProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise RoutingError(f"no provider adapter registered as {name!r}")
        return provider

    async def complete(
        self, messages: list[Message], model_or_hint: str, tenant_id: str | None = None
    ) -> CompletionResult:
        """Resolve `model_or_hint` and generate a completion on the routed provider.

        A cache hit is returned verbatim — no model call, no spend, no cap
        check; misses take the full metered path and populate the cache.
        """
        candidates = self._route_table.candidates(model_or_hint)
        primary = candidates[0]
        hint_label = primary.hint or "none"
        key: str | None = None
        if self._cache is not None:
            key = cache_key(primary.provider, primary.model, messages)
            cached = await self._cache.get(key)
            if cached is not None:
                metrics.cache_hits_total.labels(hint_label).inc()
                return cached
            metrics.cache_misses_total.labels(hint_label).inc()

        if self._meter is not None and tenant_id is not None:
            await self._meter.check_cap(tenant_id)
            await self._meter.check_signup_call_limit(tenant_id, primary.hint)

        result, served_by = await self._complete_with_failover(messages, candidates)
        if self._meter is not None and tenant_id is not None:
            await self._meter.record(
                tenant_id,
                served_by.provider,
                served_by.model,
                served_by.hint,
                result.usage.tokens_in,
                result.usage.tokens_out,
            )
        if self._cache is not None and key is not None:
            await self._cache.set(key, result)
        return result

    async def _complete_with_failover(
        self, messages: list[Message], candidates: list[Resolution]
    ) -> tuple[CompletionResult, Resolution]:
        """Try each candidate in order (skipping tripped providers), with retries.

        Raises `ProviderError` only when every candidate is exhausted.
        """
        last_error: ProviderError | None = None
        for candidate in candidates:
            if not self._health.is_available(candidate.provider):
                continue
            provider = self._provider_for(candidate.provider)
            for attempt in range(self._retry_attempts):
                try:
                    result = await provider.complete(messages, candidate.model)
                except ProviderError as exc:
                    last_error = exc
                    self._health.record_failure(candidate.provider)
                    if attempt + 1 < self._retry_attempts:
                        await self._sleep(self._backoff_seconds * (2**attempt))
                else:
                    self._health.record_success(candidate.provider)
                    return result, candidate
        raise ProviderError(
            f"all providers exhausted for candidates {[(c.provider, c.model) for c in candidates]}"
        ) from last_error

    async def embed(self, texts: list[str], tenant_id: str | None = None) -> list[list[float]]:
        """Embed texts via the provider routed for `hint:embed`."""
        resolution = self._route_table.resolve("hint:embed")
        if self._meter is not None and tenant_id is not None:
            await self._meter.check_cap(tenant_id)
            await self._meter.check_signup_call_limit(tenant_id, "embed")
        vectors = await self._provider_for(resolution.provider).embed(texts)
        if self._meter is not None and tenant_id is not None:
            tokens_in = sum(math.ceil(len(text) / 4) for text in texts)
            await self._meter.record(
                tenant_id, resolution.provider, resolution.model, "embed", tokens_in, 0
            )
        return vectors


def build_gateway(
    settings: Settings,
    meter: "UsageMeter | None" = None,
    cache: ResponseCache | None = None,
) -> ModelGateway:
    """Construct the gateway for `settings`.

    Mock mode (default): every hint served by the deterministic mock provider.
    Real mode (`MOCK_PROVIDERS=false`): every hint except `embed` routes to
    Anthropic (needs `ANTHROPIC_API_KEY`); `embed` routes to OpenRouter's
    OpenAI-compatible `/embeddings` endpoint if `OPENROUTER_API_KEY` is set
    (Anthropic has no embeddings API, M4-2), else falls back to the mock
    BoW embedder.
    """
    if settings.mock_providers:
        providers: dict[str, ModelProvider] = {
            "mock": MockProvider(embedding_dim=settings.embedding_dim)
        }
        return ModelGateway(
            providers, RouteTable(mock_route_table(), default_provider="mock"), meter, cache
        )

    if not settings.anthropic_api_key:
        raise RuntimeError(
            "MOCK_PROVIDERS=false requires ANTHROPIC_API_KEY to be set "
            "(external-cost human gate, ADR-0013)."
        )
    from neuralgram.router.providers import AnthropicProvider, OpenAIProvider

    providers = {
        "mock": MockProvider(embedding_dim=settings.embedding_dim),
        "anthropic": AnthropicProvider(api_key=settings.anthropic_api_key),
    }
    routes: dict[str, tuple[str, str]] = {
        hint: ("anthropic", settings.anthropic_model) for hint in HINTS if hint != "embed"
    }
    if settings.openrouter_api_key:
        providers["openrouter"] = OpenAIProvider(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api",
            embedding_model=settings.openrouter_embedding_model,
        )
        routes["embed"] = ("openrouter", settings.openrouter_embedding_model)
    else:
        routes["embed"] = ("mock", "mock-embed")
    return ModelGateway(providers, RouteTable(routes, default_provider="anthropic"), meter, cache)
