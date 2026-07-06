"""API dependencies: authentication and tenant scoping (C5, ADR-0006)."""

import hmac

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


async def require_tenant(request: Request, api_key: str | None = Security(_api_key_header)) -> str:
    """Resolve the calling tenant from the `x-api-key` header.

    Compares keys in constant time; raises 401 when the key is missing or
    unknown. The key itself is never logged.
    """
    if api_key:
        for configured_key, tenant_id in request.app.state.settings.api_keys.items():
            if hmac.compare_digest(configured_key, api_key):
                return str(tenant_id)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API key"
    )
