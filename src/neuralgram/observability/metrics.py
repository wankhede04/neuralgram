"""Prometheus metrics registry and ASGI exposition app (C8)."""

from typing import cast

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, make_asgi_app
from starlette.types import ASGIApp

registry = CollectorRegistry()

http_requests_total = Counter(
    "neuralgram_http_requests_total",
    "HTTP requests served, by method, route and status code.",
    labelnames=("method", "route", "status"),
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "neuralgram_http_request_duration_seconds",
    "HTTP request latency in seconds, by method and route.",
    labelnames=("method", "route"),
    registry=registry,
)

compression_tokens_in_total = Counter(
    "neuralgram_compression_tokens_in_total",
    "Tokens entering the compression layer, by applied rule.",
    labelnames=("rule",),
    registry=registry,
)

compression_tokens_out_total = Counter(
    "neuralgram_compression_tokens_out_total",
    "Tokens leaving the compression layer, by applied rule.",
    labelnames=("rule",),
    registry=registry,
)

queue_depth = Gauge(
    "neuralgram_queue_depth",
    "Jobs in the durable queue, by status.",
    labelnames=("status",),
    registry=registry,
)

chunks_ingested_total = Counter(
    "neuralgram_chunks_ingested_total",
    "Chunks persisted by the hot path, by tenant.",
    labelnames=("tenant",),
    registry=registry,
)

jobs_failed_total = Counter(
    "neuralgram_jobs_failed_total",
    "Jobs that exhausted retries and were marked failed, by kind.",
    labelnames=("kind",),
    registry=registry,
)

cache_hits_total = Counter(
    "neuralgram_cache_hits_total",
    "Prompt/response cache hits, by hint.",
    labelnames=("hint",),
    registry=registry,
)

cache_misses_total = Counter(
    "neuralgram_cache_misses_total",
    "Prompt/response cache misses, by hint.",
    labelnames=("hint",),
    registry=registry,
)

model_tokens_total = Counter(
    "neuralgram_model_tokens_total",
    "Model tokens by tenant, hint, and direction (in/out).",
    labelnames=("tenant", "hint", "direction"),
    registry=registry,
)

model_cost_usd_total = Counter(
    "neuralgram_model_cost_usd_total",
    "Model spend in USD by tenant and hint.",
    labelnames=("tenant", "hint"),
    registry=registry,
)

compression_reduction_pct = Histogram(
    "neuralgram_compression_reduction_pct",
    "Per-call token reduction percentage, by applied rule.",
    labelnames=("rule",),
    buckets=(0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
    registry=registry,
)


def metrics_app() -> ASGIApp:
    """Return the ASGI app that serves this registry at /metrics."""
    return cast(ASGIApp, make_asgi_app(registry=registry))
