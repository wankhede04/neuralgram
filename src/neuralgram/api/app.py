"""FastAPI application factory for the Neuralgram service layer (C5)."""

from fastapi import FastAPI

from neuralgram import __version__
from neuralgram.common.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the Neuralgram FastAPI application with all routes registered.

    Uses `settings` when given (tests), otherwise the process-wide
    environment-sourced settings. No side effects beyond route registration.
    """
    app = FastAPI(title="Neuralgram", version=__version__)
    app.state.settings = settings or get_settings()

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe: returns service status and version."""
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
