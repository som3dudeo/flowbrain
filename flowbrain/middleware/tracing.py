"""
Request tracing middleware — adds a unique request ID to every request
and logs structured request/response data.

Every response gets an X-Request-ID header. If the caller sends one,
it's reused (for distributed tracing). Otherwise a new UUID is generated.

Log format:
  [request_id] METHOD /path status_code duration_ms
"""

import uuid
import time
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("flowbrain.requests")


class TracingMiddleware(BaseHTTPMiddleware):
    """Adds request ID and structured access logging."""

    async def dispatch(self, request: Request, call_next):
        # Reuse caller-provided request ID or generate one
        request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"

        # Attach to request state so endpoints can read it
        request.state.request_id = request_id

        t0 = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - t0) * 1000)

        # Add to response header
        response.headers["X-Request-ID"] = request_id

        # Structured log
        client_ip = request.client.host if request.client else "-"
        logger.info(
            "[%s] %s %s %s %dms client=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            client_ip,
        )

        return response
