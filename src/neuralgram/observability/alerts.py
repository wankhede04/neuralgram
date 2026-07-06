"""Alert rules (C8, M5-4), evaluatable against the live metric registry.

The thresholds here are the single source of truth; `ops/alerts.yml`
mirrors them as Prometheus rules for the deployed stack, and the chaos
test proves a rule actually fires when its failure is induced.
"""

from collections.abc import Callable
from dataclasses import dataclass

from prometheus_client import CollectorRegistry

QUEUE_BACKLOG_THRESHOLD = 100
LATENCY_AVG_THRESHOLD_SECONDS = 1.0


def _sample(registry: CollectorRegistry, name: str, labels: dict[str, str]) -> float:
    return registry.get_sample_value(name, labels) or 0.0


def _total(registry: CollectorRegistry, name: str, label: str) -> float:
    total = 0.0
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name == name:
                total += sample.value
    return total


@dataclass(frozen=True)
class AlertRule:
    """One alert: fires when `predicate(registry)` is true."""

    name: str
    description: str
    predicate: Callable[[CollectorRegistry], bool]


def _job_failures_present(registry: CollectorRegistry) -> bool:
    return _total(registry, "neuralgram_jobs_failed_total", "kind") > 0


def _queue_backlog_high(registry: CollectorRegistry) -> bool:
    return (
        _sample(registry, "neuralgram_queue_depth", {"status": "queued"}) > QUEUE_BACKLOG_THRESHOLD
    )


def _http_latency_high(registry: CollectorRegistry) -> bool:
    total = _total(registry, "neuralgram_http_request_duration_seconds_sum", "route")
    count = _total(registry, "neuralgram_http_request_duration_seconds_count", "route")
    return count > 0 and (total / count) > LATENCY_AVG_THRESHOLD_SECONDS


RULES: tuple[AlertRule, ...] = (
    AlertRule(
        "NeuralgramJobFailures",
        "One or more jobs exhausted retries and were marked failed.",
        _job_failures_present,
    ),
    AlertRule(
        "NeuralgramQueueBacklogHigh",
        f"More than {QUEUE_BACKLOG_THRESHOLD} jobs are waiting in the queue.",
        _queue_backlog_high,
    ),
    AlertRule(
        "NeuralgramHttpLatencyHigh",
        f"Mean HTTP latency exceeds {LATENCY_AVG_THRESHOLD_SECONDS}s.",
        _http_latency_high,
    ),
)


def evaluate_alerts(registry: CollectorRegistry) -> list[str]:
    """Names of all rules currently firing against `registry`."""
    return [rule.name for rule in RULES if rule.predicate(registry)]
