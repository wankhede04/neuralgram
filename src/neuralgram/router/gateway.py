"""Model gateway (C4): the single integration point for all model access.

Only the mock provider exists for now. Real provider adapters are gated
work (external cost / D3 legality) and land in M2-3 / M4-2.
"""

import hashlib
from typing import Protocol

from pydantic import BaseModel

from neuralgram.common.config import Settings


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


def _hash_floats(seed: str, dim: int) -> list[float]:
    """Expand `seed` into `dim` deterministic floats in [-1, 1) via SHA-256 blocks."""
    values: list[float] = []
    block = 0
    while len(values) < dim:
        digest = hashlib.sha256(f"{seed}:{block}".encode()).digest()
        values.extend(byte / 128.0 - 1.0 for byte in digest)
        block += 1
    return values[:dim]


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
        """Return one deterministic hash-derived vector per input text."""
        return [_hash_floats(text, self._embedding_dim) for text in texts]


class ModelGateway:
    """Routes `complete`/`embed` calls to the configured provider."""

    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    async def complete(self, messages: list[Message], model_or_hint: str) -> CompletionResult:
        """Generate a completion via the active provider."""
        return await self._provider.complete(messages, model_or_hint)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via the active provider."""
        return await self._provider.embed(texts)


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
    return ModelGateway(MockProvider(embedding_dim=settings.embedding_dim))
