"""Tests for durable state (SQLite)."""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_record_and_retrieve_run(tmp_path, monkeypatch):
    """Runs should persist in SQLite and be retrievable."""
    # Point config to temp dir
    monkeypatch.setenv("FLOWBRAIN_ROOT", str(tmp_path))

    # Reset config singleton
    import flowbrain.config.loader as loader
    loader._config = None

    from flowbrain.state.db import record_run, get_recent_runs, new_run_id

    rid = new_run_id()
    record_run(
        run_id=rid,
        intent="send email to test@example.com",
        workflow_id="wf_123",
        workflow_name="Send Gmail",
        confidence=0.88,
        success=True,
    )

    runs = get_recent_runs(limit=5)
    assert len(runs) >= 1
    assert runs[0]["intent"] == "send email to test@example.com"
    assert runs[0]["workflow_name"] == "Send Gmail"

    # Cleanup
    loader._config = None


def test_record_preview(tmp_path, monkeypatch):
    """Previews should persist."""
    monkeypatch.setenv("FLOWBRAIN_ROOT", str(tmp_path))

    import flowbrain.config.loader as loader
    loader._config = None

    from flowbrain.state.db import record_preview, get_recent_previews, new_preview_id

    pid = new_preview_id()
    record_preview(
        preview_id=pid,
        intent="post to slack #general",
        workflow_id="wf_456",
        workflow_name="Post Slack Message",
        confidence=0.75,
        risk_level="high",
        systems_affected=["Slack"],
    )

    previews = get_recent_previews(limit=5)
    assert len(previews) >= 1
    assert previews[0]["workflow_name"] == "Post Slack Message"

    loader._config = None
