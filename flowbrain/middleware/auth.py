"""
API key authentication middleware for FlowBrain.

Security model:
  - If FLOWBRAIN_API_KEY is not set, auth is DISABLED (open access).
    This is the default for local development.
  - If FLOWBRAIN_API_KEY is set, all POST endpoints require
    `Authorization: Bearer <key>` or `X-API-Key: <key>`.
  - GET endpoints (/status, /agents, /docs, /, /openapi.json) are always
    exempt so health checks and the web UI work without a key.
  - Localhost requests (127.0.0.1 / ::1) can optionally bypass auth
    via FLOWBRAIN_AUTH_LOCALHOST_BYPASS=true (default: false).

Usage:
    from flowbrain.middleware.auth import AuthMiddleware
    app.add_middleware(AuthMiddleware)
"""

import os
import secrets
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Endpoints that never require auth
_PUBLIC_PATHS = frozenset({
    "/status", "/agents", "/docs", "/openapi.json", "/redoc", "/",
})

# Paths that start with these prefixes are public (FastAPI generated docs)
_PUBLIC_PREFIXES = ("/docs", "/openapi", "/redoc")


def _get_api_key() -> str | None:
    """Return the configured API key, or None if auth is disabled."""
    return os.getenv("FLOWBRAIN_API_KEY") or None


def _localhost_bypass_enabled() -> bool:
    return os.getenv("FLOWBRAIN_AUTH_LOCALHOST_BYPASS", "false").lower() in ("true", "1", "yes")


def _is_localhost(client_host: str | None) -> bool:
    if not client_host:
        return False
    return client_host in ("127.0.0.1", "::1", "localhost")


class AuthMiddleware(BaseHTTPMiddleware):
    """
    FastAPI/Starlette middleware that enforces API key authentication.

    Reads the key from the Authorization header (Bearer scheme) or
    X-API-Key header. Uses constant-time comparison to prevent timing attacks.
    """

    async def dispatch(self, request: Request, call_next):
        api_key = _get_api_key()

        # Auth disabled — pass through
        if api_key is None:
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"

        # Public endpoints — always allowed
        if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        # GET requests to unknown paths — allow (web UI assets, etc.)
        if request.method == "GET":
            return await call_next(request)

        # Localhost bypass
        client_host = request.client.host if request.client else None
        if _localhost_bypass_enabled() and _is_localhost(client_host):
            return await call_next(request)

        # Extract key from request
        provided_key = _extract_key(request)

        if not provided_key:
            logger.warning("Auth failed: no key provided from %s for %s %s",
                           client_host, request.method, path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required. Provide API key via Authorization: Bearer <key> or X-API-Key header."},
            )

        if not secrets.compare_digest(provided_key, api_key):
            logger.warning("Auth failed: invalid key from %s for %s %s",
                           client_host, request.method, path)
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API key."},
            )

        return await call_next(request)


def _extract_key(request: Request) -> str | None:
    """Extract API key from Authorization or X-API-Key header."""
    # Try Authorization: Bearer <key>
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    # Try X-API-Key: <key>
    return request.headers.get("x-api-key")
