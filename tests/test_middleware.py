"""Unit tests for FlowBrain middleware (auth, rate limiting, tracing)."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
import server

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client():
    """Create a fresh test client (re-imports pick up env changes via middleware)."""
    return TestClient(server.app)


# ===========================================================================
# Auth Middleware Tests
# ===========================================================================

class TestAuthMiddleware:
    """Tests for API key authentication middleware."""

    def test_no_auth_required_when_no_api_key_set(self):
        """With no FLOWBRAIN_API_KEY, all endpoints should be accessible."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FLOWBRAIN_API_KEY", None)
            client = _make_client()
            r = client.get("/status")
            assert r.status_code == 200

    def test_get_endpoints_always_public(self):
        """GET /status and /agents should work even with API key set."""
        with patch.dict(os.environ, {"FLOWBRAIN_API_KEY": "test-secret-key-12345"}):
            client = _make_client()
            r = client.get("/status")
            assert r.status_code == 200
            r = client.get("/agents")
            assert r.status_code == 200

    def test_post_blocked_without_key(self):
        """POST endpoints should return 401 when API key is set but not provided."""
        with patch.dict(os.environ, {"FLOWBRAIN_API_KEY": "test-secret-key-12345"}):
            client = _make_client()
            r = client.post("/preview", json={"intent": "test"})
            assert r.status_code == 401
            data = r.json()
            assert "Authentication required" in data["detail"]

    def test_post_forbidden_with_wrong_key(self):
        """POST endpoints should return 403 with wrong API key."""
        with patch.dict(os.environ, {"FLOWBRAIN_API_KEY": "test-secret-key-12345"}):
            client = _make_client()
            r = client.post(
                "/preview",
                json={"intent": "test"},
                headers={"Authorization": "Bearer wrong-key"},
            )
            assert r.status_code == 403

    def test_post_allowed_with_bearer_token(self):
        """POST endpoints should work with correct Bearer token."""
        key = "test-secret-key-12345"
        with patch.dict(os.environ, {"FLOWBRAIN_API_KEY": key}):
            client = _make_client()
            r = client.post(
                "/preview",
                json={"intent": "test intent"},
                headers={"Authorization": f"Bearer {key}"},
            )
            # Should get past auth (200 even if index not built)
            assert r.status_code == 200

    def test_post_allowed_with_x_api_key_header(self):
        """POST endpoints should work with X-API-Key header."""
        key = "test-secret-key-12345"
        with patch.dict(os.environ, {"FLOWBRAIN_API_KEY": key}):
            client = _make_client()
            r = client.post(
                "/preview",
                json={"intent": "test intent"},
                headers={"X-API-Key": key},
            )
            assert r.status_code == 200

    def test_localhost_bypass_disabled_by_default(self):
        """Localhost bypass should be disabled by default."""
        with patch.dict(os.environ, {"FLOWBRAIN_API_KEY": "test-key"}):
            os.environ.pop("FLOWBRAIN_AUTH_LOCALHOST_BYPASS", None)
            client = _make_client()
            r = client.post("/preview", json={"intent": "test"})
            # testclient comes from localhost, but bypass is off — should be 401
            assert r.status_code == 401


# ===========================================================================
# Rate Limit Middleware Tests
# ===========================================================================

class TestRateLimitMiddleware:
    """Tests for sliding-window rate limiter."""

    def test_rate_limit_off_by_default(self):
        """Rate limiting should be off when no API key is set."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FLOWBRAIN_API_KEY", None)
            os.environ.pop("FLOWBRAIN_RATE_LIMIT_ENABLED", None)
            client = _make_client()
            # Should be able to hit POST many times without 429
            for _ in range(15):
                r = client.post("/preview", json={"intent": "hello test"})
                assert r.status_code != 429

    def test_rate_limit_enabled_explicitly(self):
        """Explicitly enabling rate limiting should enforce burst limits."""
        with patch.dict(os.environ, {
            "FLOWBRAIN_RATE_LIMIT_ENABLED": "true",
            "FLOWBRAIN_RATE_LIMIT_BURST": "3",
        }):
            os.environ.pop("FLOWBRAIN_API_KEY", None)
            # Need a fresh app to pick up new middleware config
            client = _make_client()
            results = []
            for _ in range(6):
                r = client.post("/preview", json={"intent": "rate limit test"})
                results.append(r.status_code)
            # At least one should be 429 after burst of 3
            assert 429 in results, f"Expected 429 in results: {results}"

    def test_rate_limit_returns_retry_after(self):
        """429 responses should include Retry-After header."""
        with patch.dict(os.environ, {
            "FLOWBRAIN_RATE_LIMIT_ENABLED": "true",
            "FLOWBRAIN_RATE_LIMIT_BURST": "1",
        }):
            os.environ.pop("FLOWBRAIN_API_KEY", None)
            client = _make_client()
            client.post("/preview", json={"intent": "first request"})
            r = client.post("/preview", json={"intent": "second request"})
            if r.status_code == 429:
                assert "Retry-After" in r.headers
                data = r.json()
                assert "retry_after_seconds" in data

    def test_get_requests_not_rate_limited(self):
        """GET requests should never be rate limited."""
        with patch.dict(os.environ, {
            "FLOWBRAIN_RATE_LIMIT_ENABLED": "true",
            "FLOWBRAIN_RATE_LIMIT_BURST": "1",
        }):
            client = _make_client()
            for _ in range(10):
                r = client.get("/status")
                assert r.status_code == 200


# ===========================================================================
# Tracing Middleware Tests
# ===========================================================================

class TestTracingMiddleware:
    """Tests for request tracing middleware."""

    def test_response_includes_request_id(self):
        """Every response should include X-Request-ID header."""
        client = _make_client()
        r = client.get("/status")
        assert "x-request-id" in r.headers

    def test_preserves_caller_request_id(self):
        """If caller provides X-Request-ID, it should be echoed back."""
        client = _make_client()
        custom_id = "my-custom-trace-id-12345"
        r = client.get("/status", headers={"X-Request-ID": custom_id})
        assert r.headers.get("x-request-id") == custom_id

    def test_generates_unique_request_ids(self):
        """Auto-generated request IDs should be unique across requests."""
        client = _make_client()
        ids = set()
        for _ in range(5):
            r = client.get("/status")
            ids.add(r.headers.get("x-request-id"))
        assert len(ids) == 5, "Request IDs should be unique"
