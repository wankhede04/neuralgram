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


def metrics_app() -> ASGIApp:
    """Return the ASGI app that serves this registry at /metrics."""
    return cast(ASGIApp, make_asgi_app(registry=registry))
