"""Integration-ish checks for agent-manager endpoints."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
import server


client = TestClient(server.app)


def test_agents_endpoint():
    r = client.get('/agents')
    assert r.status_code == 200
    data = r.json()
    assert data['count'] >= 4
    assert any(agent['id'] == 'coding-agent' for agent in data['agents'])


def test_route_endpoint():
    r = client.post('/route', json={'intent': 'fix this repository bug'})
    assert r.status_code == 200
    data = r.json()
    assert data['selected_agent']['id'] == 'coding-agent'
    assert data['execution_mode'] == 'acp'
