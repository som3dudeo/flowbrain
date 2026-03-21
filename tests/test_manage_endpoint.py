"""Integration tests for the /manage agent-manager endpoint."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
import server

client = TestClient(server.app)


def test_manage_routes_to_workflow_agent():
    """Workflow intents should produce a workflow_result."""
    r = client.post("/manage", json={"intent": "send slack notification"})
    assert r.status_code == 200
    data = r.json()
    assert data["route"]["execution_mode"] == "workflow"
    assert "workflow_result" in data
    assert "delegation" not in data


def test_manage_routes_to_coding_agent():
    """Coding intents should produce a delegation plan, not a workflow result."""
    r = client.post("/manage", json={"intent": "fix this repo bug and add tests"})
    assert r.status_code == 200
    data = r.json()
    assert data["route"]["selected_agent"]["id"] == "coding-agent"
    assert "delegation" in data
    assert data["delegation"]["handler"] == "acp"
    assert data["delegation"]["execution_ready"] is True
    assert data["delegation"]["protocol"] == "openclaw-skill"
    assert "tool_call" in data["delegation"]
    assert data["delegation"]["tool_call"]["type"] == "coding-session"


def test_manage_routes_to_research_agent():
    """Research intents should produce a research delegation plan."""
    r = client.post("/manage", json={"intent": "research the best database for our project"})
    assert r.status_code == 200
    data = r.json()
    assert data["route"]["selected_agent"]["id"] == "research-agent"
    assert data["delegation"]["handler"] == "analysis"
    assert data["delegation"]["requires_human_approval"] is False


def test_manage_routes_to_openclaw_agent():
    """OpenClaw orchestration intents should produce an openclaw delegation plan."""
    r = client.post("/manage", json={"intent": "orchestrate agents across openclaw sessions"})
    assert r.status_code == 200
    data = r.json()
    assert data["route"]["selected_agent"]["id"] == "openclaw-ops-agent"
    assert data["delegation"]["protocol"] == "openclaw-native"


def test_manage_workflow_path_includes_safety_info():
    """Workflow path should include risk and confidence info."""
    r = client.post("/manage", json={"intent": "send email to alice@example.com"})
    assert r.status_code == 200
    data = r.json()
    wf = data.get("workflow_result", {})
    # Should have safety fields
    assert "risk_level" in wf or "message" in wf


def test_manage_empty_intent_rejected():
    """Empty intent should be rejected with 422."""
    r = client.post("/manage", json={"intent": ""})
    assert r.status_code == 422


def test_manage_too_long_intent_rejected():
    """Oversized intent should be rejected by pydantic validation."""
    r = client.post("/manage", json={"intent": "a" * 2001})
    assert r.status_code == 422


def test_manage_delegation_has_fallback_message():
    """Non-workflow delegations must include a user-facing fallback message."""
    r = client.post("/manage", json={"intent": "fix the python tests"})
    assert r.status_code == 200
    data = r.json()
    if "delegation" in data:
        assert "fallback_message" in data
        assert len(data["fallback_message"]) > 0
