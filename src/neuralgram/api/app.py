"""FastAPI application factory for the Neuralgram service layer (C5)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from neuralgram import __version__
from neuralgram.api.routes_memory import router as memory_router
from neuralgram.common.config import Settings, get_settings
from neuralgram.common.db import build_engine, build_session_factory
from neuralgram.memory.extraction import Extractor
from neuralgram.memory.queue import JobQueue
from neuralgram.memory.store import ContentStore
from neuralgram.memory.trees import SourceTree
from neuralgram.memory.workers import WorkerPool
from neuralgram.observability.logging import configure_logging
from neuralgram.observability.metrics import metrics_app
from neuralgram.observability.middleware import RequestContextMiddleware
from neuralgram.observability.tracing import instrument_app, setup_tracing
from neuralgram.router.gateway import build_gateway


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = build_engine(settings)
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.content_store = ContentStore(app.state.session_factory, Path(settings.vault_path))
    app.state.queue = JobQueue(app.state.session_factory)
    app.state.gateway = build_gateway(settings)
    extractor = Extractor(app.state.session_factory, app.state.gateway, queue=app.state.queue)
    tree = SourceTree(app.state.session_factory, app.state.gateway)
    app.state.worker_pool = WorkerPool(
        app.state.queue,
        {
            "extract_chunk": extractor.extract_chunk,
            "append_buffer": tree.append_buffer,
            "flush_stale": tree.flush_stale,
        },
    )
    await app.state.worker_pool.start()
    try:
        yield
    finally:
        await app.state.worker_pool.stop()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the Neuralgram FastAPI application with all routes registered.

    Uses `settings` when given (tests), otherwise the process-wide
    environment-sourced settings. Configures logging/tracing (both
    idempotent), mounts /metrics, and wires the DB engine + content store
    through the lifespan (no connection opened until first use).
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    setup_tracing()

    app = FastAPI(title="Neuralgram", version=__version__, lifespan=_lifespan)
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    app.mount("/metrics", metrics_app())
    app.include_router(memory_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe: returns service status and version."""
        return {"status": "ok", "version": __version__}

    instrument_app(app)
    return app


app = create_app()
