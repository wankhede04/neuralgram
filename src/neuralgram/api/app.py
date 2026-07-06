"""FastAPI application factory for the Neuralgram service layer (C5)."""

from fastapi import FastAPI

from neuralgram import __version__


def create_app() -> FastAPI:
    """Build the Neuralgram FastAPI application with all routes registered.

    Returns a configured, ready-to-serve application instance. No side
    effects beyond route registration.
    """
    app = FastAPI(title="Neuralgram", version=__version__)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe: returns service status and version."""
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
