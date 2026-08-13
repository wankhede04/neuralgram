"""Unit tests for the /health endpoint (P0-1 acceptance)."""

from fastapi.testclient import TestClient

from neuralgram import __version__
from neuralgram.api.app import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_health_allows_head() -> None:
    """Uptime monitors commonly probe with HEAD, not GET -- a plain
    @app.get route does not automatically accept it in Starlette."""
    client = TestClient(create_app())
    response = client.head("/health")
    assert response.status_code == 200
