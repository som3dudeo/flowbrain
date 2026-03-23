"""Tests for local outcome metrics and status surfaces."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import flowbrain.config.loader as loader
from flowbrain.state.db import record_run, record_preview, new_run_id, new_preview_id, get_outcome_metrics
import server


client = TestClient(server.app)


def test_outcome_metrics_roll_up_state(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWBRAIN_ROOT", str(tmp_path))
    loader._config = None

    record_run(
        run_id=new_run_id(),
        intent="preview only",
        auto_execute=False,
        success=False,
        duration_ms=100,
        risk_level="low",
    )
    record_run(
        run_id=new_run_id(),
        intent="needs webhook",
        auto_execute=True,
        success=False,
        needs_webhook=True,
        duration_ms=200,
        risk_level="medium",
    )
    record_run(
        run_id=new_run_id(),
        intent="executed",
        auto_execute=True,
        success=True,
        duration_ms=300,
        risk_level="low",
    )
    record_preview(
        preview_id=new_preview_id(),
        intent="blocked preview",
        blocked=True,
        risk_level="high",
    )

    metrics = get_outcome_metrics()
    assert metrics["total_runs"] == 3
    assert metrics["auto_execute_requests"] == 2
    assert metrics["executed_successes"] == 1
    assert metrics["missing_webhook_blocks"] == 1
    assert metrics["preview_only_runs"] == 1
    assert metrics["total_previews"] == 1
    assert metrics["blocked_previews"] == 1
    assert metrics["executed_success_rate"] == 0.5
    assert metrics["risk_breakdown"]["low"] == 2

    loader._config = None


def test_status_and_metrics_endpoints_include_outcomes():
    status = client.get("/status")
    assert status.status_code == 200
    status_data = status.json()
    assert "outcomes" in status_data
    assert "observability" in status_data
    assert status_data["observability"]["metrics_endpoint"] == "/metrics"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    metrics_data = metrics.json()
    assert "metrics" in metrics_data
    assert "how_to_use" in metrics_data
