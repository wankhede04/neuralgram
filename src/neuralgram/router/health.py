"""Provider health tracking for failover (C4, M4-2).

A provider is marked down after `failure_threshold` consecutive failures
and skipped until `cooldown_seconds` elapse; any success resets it.
"""

import time
from collections.abc import Callable

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 30.0


class ProviderHealth:
    """Consecutive-failure circuit breaker per provider name."""

    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._consecutive_failures: dict[str, int] = {}
        self._down_until: dict[str, float] = {}

    def record_success(self, name: str) -> None:
        """Reset the provider's failure count and clear any cooldown."""
        self._consecutive_failures[name] = 0
        self._down_until.pop(name, None)

    def record_failure(self, name: str) -> None:
        """Count a failure; trip the breaker at the threshold."""
        count = self._consecutive_failures.get(name, 0) + 1
        self._consecutive_failures[name] = count
        if count >= self._threshold:
            self._down_until[name] = self._clock() + self._cooldown

    def is_available(self, name: str) -> bool:
        """False while the provider is inside its cooldown window."""
        down_until = self._down_until.get(name)
        if down_until is None:
            return True
        if self._clock() >= down_until:
            self._down_until.pop(name, None)
            self._consecutive_failures[name] = 0
            return True
        return False
