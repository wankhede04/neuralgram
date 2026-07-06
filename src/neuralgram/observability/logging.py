"""Structured JSON logging with trace correlation (C8, standards §7)."""

import logging

import structlog
from opentelemetry import trace


def _add_trace_ids(
    logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Attach the active OTel trace/span IDs to every log line, when present."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def configure_logging(log_level: str) -> None:
    """Configure structlog to emit JSON lines at `log_level`. Idempotent."""
    logging.basicConfig(level=log_level.upper(), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_trace_ids,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(log_level.upper())
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.types.FilteringBoundLogger:
    """Return a named structured logger."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
