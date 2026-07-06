"""OpenTelemetry tracing setup (C8): spans across API -> handler and beyond."""

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider

_SERVICE_NAME = "neuralgram"


def setup_tracing(span_processor: SpanProcessor | None = None) -> TracerProvider:
    """Install a process-wide TracerProvider and return it.

    `span_processor` lets tests capture spans in memory; production
    exporters are wired here later (OTLP is an ops decision, M5-4).
    Safe to call once per process; subsequent calls return the existing
    provider unchanged.
    """
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        if span_processor is not None:
            current.add_span_processor(span_processor)
        return current

    provider = TracerProvider(resource=Resource.create({"service.name": _SERVICE_NAME}))
    if span_processor is not None:
        provider.add_span_processor(span_processor)
    trace.set_tracer_provider(provider)
    return provider


def instrument_app(app: FastAPI) -> None:
    """Attach OTel ASGI instrumentation so every request opens a server span."""
    FastAPIInstrumentor.instrument_app(app)
