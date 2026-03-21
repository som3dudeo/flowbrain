"""Integration tests for the /preview endpoint."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
import server

client = TestClient(server.app)


def _index_available(data: dict) -> bool:
    """Return True if the workflow index is loaded."""
    return "error" not in data or "not built" not in data.get("error", "")


def test_preview_returns_structured_response():
    """Preview should return risk, confidence, and safety info when index is available."""
    r = client.post("/preview", json={"intent": "send slack message to #general"})
    assert r.status_code == 200
    data = r.json()
    if _index_available(data):
        assert "intent" in data
        assert "risk_level" in data
        assert "confidence" in data or "confidence_pct" in data


def test_preview_has_no_side_effects():
    """Preview endpoint must never set auto_executed to true."""
    r = client.post("/preview", json={"intent": "send email to bob@example.com"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("auto_executed") is not True
    assert data.get("would_auto_execute") is not True or data.get("execution_blocked") is True


def test_preview_empty_intent():
    """Empty intent should be rejected with 422."""
    r = client.post("/preview", json={"intent": ""})
    assert r.status_code == 422


def test_preview_too_long_intent():
    """Oversized intent should be rejected."""
    r = client.post("/preview", json={"intent": "x" * 2001})
    assert r.status_code == 422


def test_preview_includes_alternatives():
    """Preview should include alternative workflows when available."""
    r = client.post("/preview", json={"intent": "send notification via slack"})
    assert r.status_code == 200
    data = r.json()
    if _index_available(data) and data.get("workflow_name"):
        assert "alternatives" in data
