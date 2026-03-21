"""Tests for safety policies — confidence gating and risk classification."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfidenceGating:
    def test_low_confidence_blocks_execution(self):
        from flowbrain.policies.confidence import should_auto_execute
        assert should_auto_execute(0.50, "low", auto_execute_requested=True) is False

    def test_high_confidence_allows_low_risk(self):
        from flowbrain.policies.confidence import should_auto_execute
        assert should_auto_execute(0.90, "low", auto_execute_requested=True) is True

    def test_high_risk_always_blocked(self):
        from flowbrain.policies.confidence import should_auto_execute
        assert should_auto_execute(0.99, "high", auto_execute_requested=True) is False

    def test_no_auto_execute_flag_blocks(self):
        from flowbrain.policies.confidence import should_auto_execute
        assert should_auto_execute(0.95, "low", auto_execute_requested=False) is False

    def test_medium_risk_needs_90_percent(self):
        from flowbrain.policies.confidence import should_auto_execute
        assert should_auto_execute(0.88, "medium", auto_execute_requested=True) is False
        assert should_auto_execute(0.91, "medium", auto_execute_requested=True) is True

    def test_should_preview_threshold(self):
        from flowbrain.policies.confidence import should_preview
        assert should_preview(0.50) is True
        assert should_preview(0.30) is False


class TestRiskClassification:
    def test_email_is_high_risk(self):
        from flowbrain.policies.risk import classify_risk, RiskLevel
        assert classify_risk(["Gmail", "Set"]) == RiskLevel.HIGH

    def test_emailsend_is_high_risk(self):
        from flowbrain.policies.risk import classify_risk, RiskLevel
        assert classify_risk(["Emailsend"]) == RiskLevel.HIGH

    def test_slack_is_high_risk(self):
        from flowbrain.policies.risk import classify_risk, RiskLevel
        assert classify_risk(["Slack", "Webhook"]) == RiskLevel.HIGH

    def test_notion_is_medium_risk(self):
        from flowbrain.policies.risk import classify_risk, RiskLevel
        assert classify_risk(["Notion", "Set"]) == RiskLevel.MEDIUM

    def test_webhook_only_is_low_risk(self):
        from flowbrain.policies.risk import classify_risk, RiskLevel
        assert classify_risk(["Webhook", "Set", "If"]) == RiskLevel.LOW

    def test_empty_nodes_is_unknown(self):
        from flowbrain.policies.risk import classify_risk, RiskLevel
        assert classify_risk([]) == RiskLevel.UNKNOWN

    def test_affected_systems(self):
        from flowbrain.policies.risk import get_affected_systems
        systems = get_affected_systems(["Gmail", "Set", "If", "Slack"])
        assert "Gmail" in systems
        assert "Slack" in systems
        assert "Set" not in systems


class TestPreview:
    def test_preview_build(self):
        from flowbrain.policies.preview import build_preview
        p = build_preview(
            intent="send email to bob",
            workflow_id="123",
            workflow_name="Send Gmail",
            confidence=0.85,
            nodes=["Gmail", "Set"],
            params={"to_email": "bob@example.com"},
        )
        assert p.risk_level == "high"
        assert p.workflow_name == "Send Gmail"
        assert "Gmail" in p.systems_affected

    def test_preview_blocks_low_confidence(self):
        from flowbrain.policies.preview import build_preview
        p = build_preview(
            intent="do something",
            workflow_id="456",
            workflow_name="Unknown",
            confidence=0.20,
            nodes=["Set"],
            params={},
        )
        assert p.execution_blocked is True
