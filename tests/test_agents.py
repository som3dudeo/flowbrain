"""Tests for FlowBrain agent-manager routing."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flowbrain.agents.registry import list_agents
from flowbrain.agents import router as agent_router
from flowbrain.agents.router import route_request


def test_builtin_agents_present():
    agents = list_agents()
    ids = {a['id'] for a in agents}
    assert 'workflow-automation' in ids
    assert 'coding-agent' in ids
    assert 'research-agent' in ids
    assert 'openclaw-ops-agent' in ids


def test_route_workflow_request():
    plan = route_request('send a slack message when the build passes')
    assert plan.selected_agent['id'] == 'workflow-automation'
    assert plan.execution_mode == 'workflow'
    assert plan.downstream_action == 'search-and-preview-n8n-workflow'


def test_route_coding_request():
    plan = route_request('fix this repo bug and add tests')
    assert plan.selected_agent['id'] == 'coding-agent'
    assert plan.execution_mode == 'acp'


def test_route_orchestration_request():
    plan = route_request('orchestrate agents across openclaw sessions')
    assert plan.selected_agent['id'] == 'openclaw-ops-agent'
    assert plan.execution_mode == 'openclaw'


def test_route_raises_when_no_agents_registered(monkeypatch):
    monkeypatch.setattr(agent_router, 'get_registry', lambda: [])
    try:
        route_request('route this somehow')
        assert False, 'Expected ValueError when no agents are registered'
    except ValueError as e:
        assert 'No agents registered' in str(e)
