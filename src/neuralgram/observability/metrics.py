"""Prometheus metrics registry and ASGI exposition app (C8)."""

from typing import cast

from prometheus_client import CollectorRegistry, Counter, Histogram, make_asgi_app
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
