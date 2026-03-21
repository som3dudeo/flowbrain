"""
In-memory sliding-window rate limiter for FlowBrain.

Limits requests per IP address with a configurable window and max count.
Uses a simple deque-based sliding window — no external dependencies.

Config (env vars):
  FLOWBRAIN_RATE_LIMIT_ENABLED  = true (default: true if API key is set, else false)
  FLOWBRAIN_RATE_LIMIT_RPM      = 60   (requests per minute per IP)
  FLOWBRAIN_RATE_LIMIT_BURST    = 10   (max burst within any 5-second window)

Rate limits only apply to POST endpoints. GET endpoints are exempt.
"""

import os
import time
import logging
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Defaults
_DEFAULT_RPM = 60
_DEFAULT_BURST = 10
_BURST_WINDOW = 5.0  # seconds
_MINUTE_WINDOW = 60.0


def _rate_limit_enabled() -> bool:
    explicit = os.getenv("FLOWBRAIN_RATE_LIMIT_ENABLED", "").lower()
    if explicit in ("true", "1", "yes"):
        return True
    if explicit in ("false", "0", "no"):
        return False
    # Default: enabled if API key is set (implies non-local deployment)
    return bool(os.getenv("FLOWBRAIN_API_KEY"))


def _get_rpm() -> int:
    return int(os.getenv("FLOWBRAIN_RATE_LIMIT_RPM", str(_DEFAULT_RPM)))


def _get_burst() -> int:
    return int(os.getenv("FLOWBRAIN_RATE_LIMIT_BURST", str(_DEFAULT_BURST)))


class _SlidingWindow:
    """Per-IP sliding window tracker."""
    __slots__ = ("timestamps",)

    def __init__(self):
        self.timestamps: deque[float] = deque()

    def _prune(self, now: float, window: float):
        cutoff = now - window
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()

    def count_in_window(self, window: float) -> int:
        self._prune(time.monotonic(), window)
        return len(self.timestamps)

    def record(self):
        self.timestamps.append(time.monotonic())


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding-window rate limiter.

    Two checks:
      1. Burst: max N requests in a 5-second window (prevents hammering)
      2. Sustained: max M requests per minute (prevents abuse)

    Evicts stale IP entries every 1000 requests to prevent memory growth.
    """

    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        self._windows: dict[str, _SlidingWindow] = defaultdict(_SlidingWindow)
        self._request_count = 0

    async def dispatch(self, request: Request, call_next):
        if not _rate_limit_enabled():
            return await call_next(request)

        # Only rate-limit POST endpoints (mutations)
        if request.method != "POST":
            return await call_next(request)

        rpm = _get_rpm()
        burst = _get_burst()
        client_ip = request.client.host if request.client else "unknown"
        window = self._windows[client_ip]

        # Check burst
        if window.count_in_window(_BURST_WINDOW) >= burst:
            logger.warning("Rate limit burst exceeded for %s", client_ip)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Max {burst} requests per {_BURST_WINDOW:.0f}s.",
                    "retry_after_seconds": _BURST_WINDOW,
                },
                headers={"Retry-After": str(int(_BURST_WINDOW))},
            )

        # Check sustained
        if window.count_in_window(_MINUTE_WINDOW) >= rpm:
            logger.warning("Rate limit RPM exceeded for %s", client_ip)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Max {rpm} requests per minute.",
                    "retry_after_seconds": 60,
                },
                headers={"Retry-After": "60"},
            )

        window.record()
        self._request_count += 1

        # Periodic cleanup of stale entries
        if self._request_count % 1000 == 0:
            self._cleanup()

        return await call_next(request)

    def _cleanup(self):
        """Remove IP entries that haven't been seen in 2 minutes."""
        now = time.monotonic()
        stale = [
            ip for ip, w in self._windows.items()
            if not w.timestamps or (now - w.timestamps[-1]) > 120
        ]
        for ip in stale:
            del self._windows[ip]
        if stale:
            logger.debug("Rate limiter: evicted %d stale IP entries", len(stale))
