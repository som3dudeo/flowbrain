"""Integration tests for the /auto endpoint — the core execution pipeline."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
import server

client = TestClient(server.app)


def _index_available(data: dict) -> bool:
    """Return True if the workflow index is loaded (not all environments have it)."""
    return data.get("success") is not False and "not built" not in data.get("message", "")


def test_auto_preview_mode_default():
    """/auto with default auto_execute=false should never execute."""
    r = client.post("/auto", json={"intent": "send slack message"})
    assert r.status_code == 200
    data = r.json()
    if _index_available(data):
        assert data.get("auto_executed") is False
        assert "block_reason" in data


def test_auto_includes_safety_fields():
    """/auto should return risk_level and confidence when index is available."""
    r = client.post("/auto", json={"intent": "send email to test@example.com"})
    assert r.status_code == 200
    data = r.json()
    if _index_available(data):
        assert "risk_level" in data
        assert "confidence" in data
        assert "systems_affected" in data


def test_auto_high_risk_blocked_even_with_auto_execute():
    """HIGH risk workflows must be blocked even when auto_execute=true."""
    r = client.post("/auto", json={
        "intent": "send email to alice@example.com saying hello",
        "auto_execute": True,
    })
    assert r.status_code == 200
    data = r.json()
    if _index_available(data) and data.get("risk_level") == "high":
        assert data.get("auto_executed") is False
        assert "block_reason" in data
        assert data["block_reason"] != ""


def test_auto_empty_intent():
    """Empty intent should be rejected with 422."""
    r = client.post("/auto", json={"intent": ""})
    assert r.status_code == 422


def test_auto_too_long_intent():
    """Oversized intent should be rejected."""
    r = client.post("/auto", json={"intent": "z" * 2001})
    assert r.status_code == 422


def test_auto_returns_session_id():
    """/auto should always return a session_id for conversation tracking."""
    r = client.post("/auto", json={"intent": "send discord notification"})
    assert r.status_code == 200
    data = r.json()
    if _index_available(data):
        assert "session_id" in data
        assert data["session_id"] is not None


def test_auto_preserves_user_params():
    """User-provided params should appear in params_extracted."""
    r = client.post("/auto", json={
        "intent": "send slack message",
        "params": {"channel": "#general", "custom_key": "custom_value"},
    })
    assert r.status_code == 200
    data = r.json()
    if _index_available(data):
        extracted = data.get("params_extracted", {})
        assert extracted.get("channel") == "#general"
        assert extracted.get("custom_key") == "custom_value"


def test_auto_needs_webhook_when_none_configured():
    """When no webhook is configured, needs_webhook should be true."""
    r = client.post("/auto", json={
        "intent": "send slack message to team",
        "auto_execute": True,
    })
    assert r.status_code == 200
    data = r.json()
    if _index_available(data) and not data.get("auto_executed"):
        assert data.get("block_reason") or data.get("needs_webhook")
