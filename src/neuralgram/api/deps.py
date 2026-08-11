"""API dependencies: authentication, RBAC roles, and tenant scoping (C5/C7).

Roles (M5-2): reader < writer < admin. Two key sources, checked in order:
1. Static `Settings.api_key_roles` (env-configured, e.g. .env's my-test-key).
2. DB-issued keys from self-serve signup/login (M5-2 extension) — looked up
   by hash via the system session factory, since no tenant context exists
   yet at this point in the request.
The actor recorded in audit logs is a SHA-256 fingerprint of the key — the
raw key is never stored or logged (ADR-0006).
"""

import hashlib
import hmac

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select

from neuralgram.api.security import hash_api_key
from neuralgram.storage.models import User

_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

ROLE_LEVELS = {"reader": 0, "writer": 1, "admin": 2}
DEFAULT_ROLE = "writer"


def key_fingerprint(api_key: str) -> str:
    """Short stable identifier for an API key; safe to store and log."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


def _resolve_static(request: Request, api_key: str) -> tuple[str, str] | None:
    """Check the env-configured API_KEYS/API_KEY_ROLES dict."""
    settings = request.app.state.settings
    for configured_key, tenant_id in settings.api_keys.items():
        if hmac.compare_digest(configured_key, api_key):
            role = settings.api_key_roles.get(configured_key, DEFAULT_ROLE)
            return str(tenant_id), role
    return None


async def _resolve_db(request: Request, api_key: str) -> tuple[str, str] | None:
    """Check DB-issued keys from self-serve signup/login.

    Skips gracefully if the app's lifespan never ran (e.g. bare unit tests
    that construct a TestClient without the `with` context manager) --
    system_session_factory won't exist yet in that case, and there is no
    DB-issued key to find regardless.
    """
    factory = getattr(request.app.state, "system_session_factory", None)
    if factory is None:
        return None
    hashed = hash_api_key(api_key)
    async with factory() as session:
        result = await session.execute(select(User).where(User.hashed_key == hashed))
        user = result.scalar_one_or_none()
    if user is None:
        return None
    return user.tenant_id, user.role


async def _resolve(request: Request, api_key: str | None) -> tuple[str, str] | None:
    """Return (tenant_id, role) for a valid key, else None."""
    if not api_key:
        return None
    return _resolve_static(request, api_key) or await _resolve_db(request, api_key)


async def require_tenant(request: Request, api_key: str | None = Security(_api_key_header)) -> str:
    """Resolve the calling tenant from the `x-api-key` header (any role).

    Stores tenant/role/actor on `request.state` for RBAC checks and audit.
    Raises 401 when the key is missing or unknown; keys are never logged.
    """
    resolved = await _resolve(request, api_key)
    if resolved is None:
        request.state.audit_actor = "invalid-key"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API key"
        )
    tenant_id, role = resolved
    request.state.is_demo_tenant = False

    demo_tenant_id = request.app.state.settings.demo_tenant_id
    if demo_tenant_id and tenant_id == demo_tenant_id:
        request.state.is_demo_tenant = True
        client_ip = request.client.host if request.client else "unknown"
        # Per-category rate limiting (ingest/search) happens at the route
        # level, not here -- keyword search and summaries need no AI call
        # and are never rate-limited at all, matching the signup tenant's
        # rule (no API call = unlimited).
        # Each demo visitor gets an isolated slice of the shared demo tenant,
        # keyed by IP, so unrelated visitors never see each other's data.
        tenant_id = f"{demo_tenant_id}-{key_fingerprint(client_ip)}"

    request.state.tenant_id = tenant_id
    request.state.role = role
    request.state.audit_actor = key_fingerprint(api_key or "")
    return tenant_id


def require_role(minimum: str) -> object:
    """Dependency factory: the caller's role must be at least `minimum`."""

    async def _check(request: Request, api_key: str | None = Security(_api_key_header)) -> str:
        tenant_id = await require_tenant(request, api_key)
        role = request.state.role
        if ROLE_LEVELS[role] < ROLE_LEVELS[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {role!r} may not perform this action (needs {minimum!r})",
            )
        return tenant_id

    return _check
