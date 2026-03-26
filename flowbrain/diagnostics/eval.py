"""Benchmark fixtures, example intents, and local evaluation helpers for FlowBrain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import re

from router import get_router

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES_PATH = _REPO_ROOT / "tests" / "benchmarks" / "fixtures.json"


def load_benchmark_fixtures() -> list[dict[str, Any]]:
    """Load the fixed intent benchmark set used for local evaluation."""
    return json.loads(_FIXTURES_PATH.read_text())


def get_example_intents() -> list[dict[str, str]]:
    """Return guided examples for first-run users and API consumers."""
    return [
        {
            "label": "Safe preview-first first win",
            "intent": "send a slack message when deploy finishes",
            "endpoint": "/preview",
            "expected_mode": "preview",
            "why": "Shows search, confidence, risk, and next_step without side effects.",
        },
        {
            "label": "Agent-manager honesty check",
            "intent": "fix this repo bug and add tests",
            "endpoint": "/manage",
            "expected_mode": "delegate",
            "why": "Shows that coding requests return a delegation plan instead of fake workflow autonomy.",
        },
        {
            "label": "High-risk messaging preview",
            "intent": "post a public update to slack about the deployment",
            "endpoint": "/preview",
            "expected_mode": "preview-blocked-or-manual",
            "why": "Shows that external messaging is treated conservatively and kept in preview-first mode.",
        },
    ]


def _normalize_token(value: str) -> str:
    text = str(value or "").lower().strip()
    text = text.replace("schedule trigger", "schedule")
    text = text.replace("google sheets", "googlesheets")
    text = text.replace("email send", "emailsend")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def _node_matches(expected: str, candidates: list[str]) -> bool:
    target = _normalize_token(expected)
    synonyms = {
        "gmail": {"gmail", "emailsend", "email", "mail"},
        "googlesheets": {"googlesheets", "sheet", "sheets"},
        "discord": {"discord"},
        "telegram": {"telegram"},
        "jira": {"jira"},
        "slack": {"slack"},
        "notion": {"notion"},
        "airtable": {"airtable"},
        "webhook": {"webhook", "httprequest", "http"},
        "scheduletrigger": {"scheduletrigger", "schedule", "cron"},
    }
    acceptable = synonyms.get(target, {target})
    return any(any(alias in cand for alias in acceptable) for cand in candidates)


def run_benchmark(top_k: int = 1) -> dict[str, Any]:
    """Run the fixed retrieval benchmark against the local index, without requiring the API server."""
    router = get_router()
    fixtures = load_benchmark_fixtures()

    if not router.is_ready:
        return {
            "ready": False,
            "fixture_count": len(fixtures),
            "passed": 0,
            "failed": len(fixtures),
            "pass_rate": 0.0,
            "results": [],
            "message": "Workflow index not built. Run `flowbrain reindex` first.",
        }

    results: list[dict[str, Any]] = []
    passed = 0

    for fixture in fixtures:
        matches = router.search(fixture["intent"], top_k=max(top_k, 1))
        top = matches[0] if matches else None
        top_nodes = [_normalize_token(n) for n in (top.nodes if top else [])]
        top_categories = [_normalize_token(c) for c in (top.categories if top else [])]
        expected_nodes = [str(n) for n in fixture.get("expected_nodes", [])]
        expected_category = str(fixture.get("expected_category", "")).lower()
        min_conf = float(fixture.get("min_confidence", 0.0))

        nodes_ok = bool(top) and all(_node_matches(exp, top_nodes) for exp in expected_nodes)
        category_ok = bool(top) and (not expected_category or not top_categories or any(_normalize_token(expected_category) in cat for cat in top_categories))
        confidence_ok = bool(top) and float(top.confidence) >= min_conf
        ok = bool(top) and nodes_ok and category_ok and confidence_ok

        if ok:
            passed += 1

        results.append({
            "intent": fixture["intent"],
            "expected_nodes": fixture.get("expected_nodes", []),
            "expected_category": fixture.get("expected_category"),
            "min_confidence": min_conf,
            "matched": bool(top),
            "top_workflow": top.name if top else None,
            "top_nodes": top.nodes if top else [],
            "top_categories": top.categories if top else [],
            "confidence": round(float(top.confidence), 3) if top else 0.0,
            "checks": {
                "nodes": nodes_ok,
                "category": category_ok,
                "confidence": confidence_ok,
            },
            "passed": ok,
        })

    total = len(results)
    failed = total - passed
    return {
        "ready": True,
        "fixture_count": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round((passed / total) if total else 0.0, 3),
        "results": results,
    }
