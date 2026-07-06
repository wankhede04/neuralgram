"""Audit trail for memory access (C7, M5-2): every /memory and /admin
request is recorded — including denials — with the actor's key fingerprint."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from neuralgram.observability.logging import get_logger
from neuralgram.storage.models import AuditEvent

logger = get_logger(__name__)

AUDITED_PREFIXES = ("/memory", "/admin")


class AuditMiddleware(BaseHTTPMiddleware):
    """Writes one audit_events row per audited request, after the response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if not request.url.path.startswith(AUDITED_PREFIXES):
            return response

        factory = getattr(request.app.state, "system_session_factory", None)
        if factory is None:  # lifespan not started (some unit-test setups)
            return response

        resource = request.url.path
        if request.url.query:
            resource = f"{resource}?{request.url.query}"
        try:
            async with factory() as session:
                session.add(
                    AuditEvent(
                        id=uuid.uuid4().hex,
                        tenant_id=getattr(request.state, "tenant_id", "unknown"),
                        actor=getattr(request.state, "audit_actor", "anonymous"),
                        action=request.method,
                        resource=resource[:512],
                        status=response.status_code,
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("audit.write_failed", resource=resource)
        return response
