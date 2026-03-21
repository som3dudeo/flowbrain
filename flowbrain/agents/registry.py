"""Built-in and optional file-backed agent registry."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    role: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    handler: str = "workflow"
    safety_mode: str = "supervised"
    preferred_runtime: str = "internal"
    keywords: list[str] = field(default_factory=list)


_BUILTIN_AGENTS = [
    AgentProfile(
        id="workflow-automation",
        name="Workflow Automation Agent",
        role="automation",
        description="Finds and runs n8n workflows for real-world actions across apps and services.",
        capabilities=["n8n", "workflow-search", "automation", "webhook-execution"],
        handler="workflow",
        safety_mode="preview-first",
        preferred_runtime="n8n",
        keywords=["workflow", "automation", "slack", "email", "notion", "jira", "telegram", "discord"],
    ),
    AgentProfile(
        id="coding-agent",
        name="Coding Agent",
        role="implementation",
        description="Handles code changes, debugging, refactors, tests, and repository tasks.",
        capabilities=["coding", "debugging", "refactor", "tests", "repo-ops"],
        handler="acp",
        safety_mode="supervised",
        preferred_runtime="acp",
        keywords=["code", "repo", "bug", "fix", "implement", "refactor", "test", "python", "javascript"],
    ),
    AgentProfile(
        id="research-agent",
        name="Research Agent",
        role="research",
        description="Investigates topics, compares options, summarizes findings, and produces briefs.",
        capabilities=["research", "analysis", "comparison", "summarization"],
        handler="analysis",
        safety_mode="safe",
        preferred_runtime="internal",
        keywords=["research", "compare", "analyze", "investigate", "summary", "brief"],
    ),
    AgentProfile(
        id="openclaw-ops-agent",
        name="OpenClaw Ops Agent",
        role="orchestration",
        description="Handles OpenClaw-native operations like reminders, sessions, cron jobs, and tool orchestration.",
        capabilities=["openclaw", "cron", "sessions", "routing", "orchestration"],
        handler="openclaw",
        safety_mode="supervised",
        preferred_runtime="openclaw",
        keywords=["openclaw", "reminder", "session", "cron", "subagent", "agent manager", "orchestrate"],
    ),
]


def _agent_file() -> Path:
    root = Path(os.getenv("FLOWBRAIN_ROOT", "") or Path.cwd())
    return root / "data" / "agents.json"


def _load_file_agents() -> list[AgentProfile]:
    path = _agent_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        agents = []
        for item in data if isinstance(data, list) else []:
            agents.append(AgentProfile(**item))
        return agents
    except Exception:
        return []


def get_registry() -> list[AgentProfile]:
    custom = _load_file_agents()
    if not custom:
        return list(_BUILTIN_AGENTS)

    by_id = {a.id: a for a in _BUILTIN_AGENTS}
    for agent in custom:
        by_id[agent.id] = agent
    return list(by_id.values())


def list_agents() -> list[dict]:
    return [asdict(a) for a in get_registry()]
