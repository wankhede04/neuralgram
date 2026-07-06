"""Unit tests: OpenAPI docs and authn behavior of the memory API (M1-7 acceptance)."""

from fastapi.testclient import TestClient

from neuralgram.api.app import create_app
from neuralgram.common.config import Settings


def _client(api_keys: dict[str, str] | None = None) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, api_keys=api_keys or {})))


def test_openapi_documents_memory_routes_and_security_scheme() -> None:
    spec = _client().get("/openapi.json").json()
    for path in ("/memory/ingest", "/memory/search", "/memory/chunks/{chunk_id}"):
        assert path in spec["paths"], f"{path} missing from OpenAPI docs"
    schemes = spec.get("components", {}).get("securitySchemes", {})
    assert any(s.get("in") == "header" and s.get("name") == "x-api-key" for s in schemes.values())


def test_requests_without_key_are_401() -> None:
    client = _client(api_keys={"real-key": "tenant-a"})
    assert client.get("/memory/search", params={"q": "x"}).status_code == 401
    assert client.get("/memory/chunks/abc").status_code == 401
    assert (
        client.post(
            "/memory/ingest", json={"source_id": "s", "payload": {"messages": []}}
        ).status_code
        == 401
    )


def test_wrong_key_is_401() -> None:
    client = _client(api_keys={"real-key": "tenant-a"})
    response = client.get("/memory/search", params={"q": "x"}, headers={"x-api-key": "wrong-key"})
    assert response.status_code == 401


def test_health_needs_no_key() -> None:
    assert _client(api_keys={"real-key": "tenant-a"}).get("/health").status_code == 200
