"""C4 hint routing: hint -> (provider, model), remappable at runtime (M4-1).

Resolution rules (spec C4): `hint:{reasoning|fast|vision|summarize|code|embed}`
resolves through the route table; any other string is treated as a concrete
model name and falls through to the default provider.
"""

from pydantic import BaseModel

from neuralgram.common.errors import RoutingError

HINTS = ("reasoning", "fast", "vision", "summarize", "code", "embed")
_HINT_PREFIX = "hint:"


class Resolution(BaseModel):
    """The outcome of routing one model_or_hint string."""

    provider: str
    model: str
    hint: str | None = None


def mock_route_table() -> dict[str, tuple[str, str]]:
    """Default table for MOCK_PROVIDERS mode: every hint served by the mock provider."""
    return {hint: ("mock", f"mock-{hint}") for hint in HINTS}


class RouteTable:
    """Mutable hint -> (provider, model) table with concrete-name fallthrough.

    `fallbacks` lists additional (provider, model) candidates per hint,
    tried in order when the primary fails (M4-2 failover).
    """

    def __init__(
        self,
        routes: dict[str, tuple[str, str]],
        default_provider: str,
        fallbacks: dict[str, list[tuple[str, str]]] | None = None,
    ) -> None:
        unknown = set(routes) - set(HINTS)
        if unknown:
            raise RoutingError(f"unknown hints in route table: {sorted(unknown)}")
        self._routes = dict(routes)
        self._default_provider = default_provider
        self._fallbacks = {k: list(v) for k, v in (fallbacks or {}).items()}

    def resolve(self, model_or_hint: str) -> Resolution:
        """Resolve a hint via the table, or fall a concrete name through to the default provider.

        Raises `RoutingError` for unknown or unrouted hints.
        """
        if model_or_hint.startswith(_HINT_PREFIX):
            hint = model_or_hint[len(_HINT_PREFIX) :]
            if hint not in HINTS:
                raise RoutingError(f"unknown hint {hint!r}; valid: {list(HINTS)}")
            if hint not in self._routes:
                raise RoutingError(f"hint {hint!r} has no route configured")
            provider, model = self._routes[hint]
            return Resolution(provider=provider, model=model, hint=hint)
        return Resolution(provider=self._default_provider, model=model_or_hint)

    def candidates(self, model_or_hint: str) -> list[Resolution]:
        """The primary resolution followed by its failover candidates, in order."""
        primary = self.resolve(model_or_hint)
        if primary.hint is None:
            return [primary]
        return [primary] + [
            Resolution(provider=p, model=m, hint=primary.hint)
            for p, m in self._fallbacks.get(primary.hint, [])
        ]

    def remap(self, hint: str, provider: str, model: str) -> None:
        """Repoint a hint at runtime (spec: route table remappable at runtime)."""
        if hint not in HINTS:
            raise RoutingError(f"cannot remap unknown hint {hint!r}")
        self._routes[hint] = (provider, model)

    def snapshot(self) -> dict[str, tuple[str, str]]:
        """Current routes (copy), for inspection/admin surfaces."""
        return dict(self._routes)
