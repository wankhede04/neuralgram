"""Model gateway (C4): the single integration point for all model access.

Only the mock provider exists for now. Real provider adapters are gated
work (external cost / D3 legality) and land in M2-3 / M4-2.
"""

import hashlib
from typing import Protocol

from pydantic import BaseModel

from neuralgram.common.config import Settings
from neuralgram.common.errors import RoutingError
from neuralgram.router.routing import RouteTable, mock_route_table


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
    """Routes `complete`/`embed` through the hint table to provider adapters (C4)."""

    def __init__(
        self,
        providers: dict[str, ModelProvider],
        route_table: RouteTable,
    ) -> None:
        self._providers = providers
        self._route_table = route_table

    @property
    def route_table(self) -> RouteTable:
        """The live route table (remappable at runtime)."""
        return self._route_table

    def _provider_for(self, name: str) -> ModelProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise RoutingError(f"no provider adapter registered as {name!r}")
        return provider

    async def complete(self, messages: list[Message], model_or_hint: str) -> CompletionResult:
        """Resolve `model_or_hint` and generate a completion on the routed provider."""
        resolution = self._route_table.resolve(model_or_hint)
        return await self._provider_for(resolution.provider).complete(messages, resolution.model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via the provider routed for `hint:embed`."""
        resolution = self._route_table.resolve("hint:embed")
        return await self._provider_for(resolution.provider).embed(texts)


def build_gateway(settings: Settings) -> ModelGateway:
    """Construct the gateway for `settings`.

    Raises `RuntimeError` if mock mode is off: real provider adapters are
    a human-gated task (external cost, D3) and do not exist yet.
    """
    if not settings.mock_providers:
        raise RuntimeError(
            "Real model providers are not available: enabling them is a human gate "
            "(external cost / D3). Set MOCK_PROVIDERS=true."
        )
    providers: dict[str, ModelProvider] = {
        "mock": MockProvider(embedding_dim=settings.embedding_dim)
    }
    return ModelGateway(providers, RouteTable(mock_route_table(), default_provider="mock"))
