"""Request-ID propagation and per-request metrics (C8)."""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from neuralgram.observability.metrics import (
    http_request_duration_seconds,
    http_requests_total,
)

REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request ID, bind it to the log context, and record HTTP metrics.

    The inbound `x-request-id` header is honored when present; the ID is
    always echoed back on the response.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER, str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        http_requests_total.labels(request.method, route_path, str(response.status_code)).inc()
        http_request_duration_seconds.labels(request.method, route_path).observe(
            time.perf_counter() - start
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
