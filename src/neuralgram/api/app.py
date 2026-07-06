"""FastAPI application factory for the Neuralgram service layer (C5)."""

from fastapi import FastAPI

from neuralgram import __version__
from neuralgram.common.config import Settings, get_settings
from neuralgram.observability.logging import configure_logging
from neuralgram.observability.metrics import metrics_app
from neuralgram.observability.middleware import RequestContextMiddleware
from neuralgram.observability.tracing import instrument_app, setup_tracing


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the Neuralgram FastAPI application with all routes registered.

    Uses `settings` when given (tests), otherwise the process-wide
    environment-sourced settings. Configures logging/tracing (both
    idempotent) and mounts the Prometheus registry at /metrics.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    setup_tracing()

    app = FastAPI(title="Neuralgram", version=__version__)
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    app.mount("/metrics", metrics_app())

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe: returns service status and version."""
        return {"status": "ok", "version": __version__}

    instrument_app(app)
    return app


app = create_app()
