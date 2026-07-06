"""API dependencies: authentication, RBAC roles, and tenant scoping (C5/C7).

Roles (M5-2): reader < writer < admin. Per-key roles come from
`Settings.api_key_roles` (default: writer). The actor recorded in audit
logs is a SHA-256 fingerprint of the key — the raw key is never stored
or logged (ADR-0006).
"""

import hashlib
import hmac

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

ROLE_LEVELS = {"reader": 0, "writer": 1, "admin": 2}
DEFAULT_ROLE = "writer"


def key_fingerprint(api_key: str) -> str:
    """Short stable identifier for an API key; safe to store and log."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


def _resolve(request: Request, api_key: str | None) -> tuple[str, str] | None:
    """Return (tenant_id, role) for a valid key, else None."""
    if not api_key:
        return None
    settings = request.app.state.settings
    for configured_key, tenant_id in settings.api_keys.items():
        if hmac.compare_digest(configured_key, api_key):
            role = settings.api_key_roles.get(configured_key, DEFAULT_ROLE)
            return str(tenant_id), role
    return None


async def require_tenant(request: Request, api_key: str | None = Security(_api_key_header)) -> str:
    """Resolve the calling tenant from the `x-api-key` header (any role).

    Stores tenant/role/actor on `request.state` for RBAC checks and audit.
    Raises 401 when the key is missing or unknown; keys are never logged.
    """
    resolved = _resolve(request, api_key)
    if resolved is None:
        request.state.audit_actor = "invalid-key"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API key"
        )
    tenant_id, role = resolved
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
