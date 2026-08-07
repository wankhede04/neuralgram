"""CORS: the browser dashboard's origin must be allowed (frontend/, M6)."""

from fastapi.testclient import TestClient

from neuralgram.api.app import create_app
from neuralgram.common.config import Settings


def test_preflight_allows_dashboard_origin() -> None:
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.options(
            "/memory/search",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
        )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "x-api-key" in allowed_headers


def test_actual_request_carries_cors_header() -> None:
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get(
            "/memory/search",
            params={"q": "x"},
            headers={"Origin": "http://localhost:5173", "x-api-key": "no-such-key"},
        )
    # 401 (bad key) is expected here -- we're only checking the CORS header is present
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
