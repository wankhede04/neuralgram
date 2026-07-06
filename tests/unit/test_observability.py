"""Unit tests for the observability skeleton (P0-6 acceptance)."""

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from neuralgram.api.app import create_app
from neuralgram.common.config import Settings
from neuralgram.observability.tracing import setup_tracing


def _client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None)))


def test_request_emits_server_span_for_route() -> None:
    exporter = InMemorySpanExporter()
    setup_tracing(SimpleSpanProcessor(exporter))
    exporter.clear()

    response = _client().get("/health")
    assert response.status_code == 200

    spans = exporter.get_finished_spans()
    server_spans = [s for s in spans if s.kind == SpanKind.SERVER]
    assert server_spans, "expected a server span for the request"
    assert any((s.attributes or {}).get("http.route") == "/health" for s in server_spans), (
        "server span should carry the handler route"
    )


def test_metrics_endpoint_is_live_and_counts_requests() -> None:
    client = _client()
    assert client.get("/health").status_code == 200

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "neuralgram_http_requests_total" in response.text
    assert 'route="/health"' in response.text


def test_request_id_is_assigned_and_echoed() -> None:
    client = _client()
    fresh = client.get("/health")
    assert fresh.headers.get("x-request-id")

    echoed = client.get("/health", headers={"x-request-id": "req-123"})
    assert echoed.headers["x-request-id"] == "req-123"
