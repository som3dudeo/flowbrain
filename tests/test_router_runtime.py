"""Runtime regression tests for router collection reload behavior."""

import os
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from router import WorkflowRouter


class _BrokenThenHealthyCollection:
    def __init__(self):
        self.count_calls = 0
        self.query_calls = 0

    def count(self):
        self.count_calls += 1
        if self.count_calls == 1:
            raise RuntimeError("stale collection handle")
        return 450

    def query(self, **kwargs):
        self.query_calls += 1
        if self.query_calls == 1:
            raise RuntimeError("stale collection handle")
        return {
            "ids": [["wf_1"]],
            "metadatas": [[{
                "name": "Post Slack notification",
                "desc": "Send a Slack message",
                "nodes": "Slack, Webhook",
                "categories": "Communication",
                "tags": "slack, notification",
                "source_url": "https://example.com/wf_1",
                "views": 12,
            }]],
            "distances": [[0.2]],
            "documents": [["Post Slack notification"]],
        }


class _HealthyCollection:
    def count(self):
        return 450

    def query(self, **kwargs):
        return {
            "ids": [["wf_1"]],
            "metadatas": [[{
                "name": "Post Slack notification",
                "desc": "Send a Slack message",
                "nodes": "Slack, Webhook",
                "categories": "Communication",
                "tags": "slack, notification",
                "source_url": "https://example.com/wf_1",
                "views": 12,
            }]],
            "distances": [[0.2]],
            "documents": [["Post Slack notification"]],
        }


def test_workflow_count_recovers_from_stale_collection(monkeypatch):
    router = WorkflowRouter()
    router._ready = True
    router._collection = _BrokenThenHealthyCollection()

    reloaded = {"count": 0}

    def fake_reload():
        reloaded["count"] += 1
        router._collection = _HealthyCollection()
        router._ready = True
        return True

    monkeypatch.setattr(router, "_reload_collection", fake_reload)

    assert router.workflow_count == 450
    assert reloaded["count"] == 1


def test_search_recovers_from_stale_collection(monkeypatch):
    router = WorkflowRouter()
    router._ready = True
    router._collection = _BrokenThenHealthyCollection()

    reloaded = {"count": 0}

    def fake_reload():
        reloaded["count"] += 1
        router._collection = _HealthyCollection()
        router._ready = True
        return True

    monkeypatch.setattr(router, "_reload_collection", fake_reload)

    results = router.search("send slack message", top_k=1)

    assert len(results) == 1
    assert results[0].name == "Post Slack notification"
    assert reloaded["count"] == 1
