"""Task-to-agent routing and execution planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from flowbrain.agents.registry import AgentProfile, get_registry


@dataclass
class AgentRoute:
    selected_agent: dict
    score: float
    reasoning: list[str] = field(default_factory=list)
    execution_mode: str = "delegate"
    requires_human_approval: bool = False
    downstream_action: str = ""
    candidate_agents: list[dict] = field(default_factory=list)


_HANDLER_ACTIONS = {
    "workflow": "search-and-preview-n8n-workflow",
    "acp": "spawn-coding-agent-session",
    "analysis": "answer-or-research-internal",
    "openclaw": "use-openclaw-native-tools",
}


_KEYWORD_BONUS = {
    "workflow": ["send", "post", "notify", "email", "slack", "discord", "telegram", "notion", "jira", "automation"],
    "acp": ["code", "repo", "implement", "debug", "fix", "refactor", "test", "build", "server"],
    "analysis": ["research", "compare", "explain", "analyze", "summarize"],
    "openclaw": ["remind", "schedule", "cron", "session", "delegate", "agent", "openclaw", "orchestrate"],
}


def _score_agent(intent: str, agent: AgentProfile) -> tuple[float, list[str]]:
    text = intent.lower().strip()
    score = 0.05
    reasons: list[str] = []

    for keyword in agent.keywords:
        if keyword.lower() in text:
            score += 0.18
            reasons.append(f"matched keyword '{keyword}'")

    for capability in agent.capabilities:
        if capability.lower() in text:
            score += 0.12
            reasons.append(f"matched capability '{capability}'")

    for keyword in _KEYWORD_BONUS.get(agent.handler, []):
        if keyword in text:
            score += 0.08
            reasons.append(f"handler '{agent.handler}' fits '{keyword}'")

    if agent.handler == "workflow" and any(x in text for x in ["workflow", "n8n", "automation"]):
        score += 0.15
        reasons.append("workflow-oriented request")
    if agent.handler == "acp" and any(x in text for x in ["repo", "fix", "implement", "debug"]):
        score += 0.15
        reasons.append("coding-oriented request")
    if agent.handler == "openclaw" and any(x in text for x in ["agent manager", "delegate", "orchestrate", "session"]):
        score += 0.18
        reasons.append("orchestration-oriented request")

    return min(score, 0.99), reasons


def route_request(intent: str) -> AgentRoute:
    if not intent or not intent.strip():
        raise ValueError("Intent cannot be empty")

    candidates = []
    best_agent: AgentProfile | None = None
    best_score = -1.0
    best_reasons: list[str] = []

    for agent in get_registry():
        score, reasons = _score_agent(intent, agent)
        payload = asdict(agent)
        payload["score"] = round(score, 3)
        payload["reasoning"] = reasons
        candidates.append(payload)
        if score > best_score:
            best_agent = agent
            best_score = score
            best_reasons = reasons

    assert best_agent is not None

    requires_human_approval = best_agent.safety_mode in {"preview-first", "supervised"}
    downstream_action = _HANDLER_ACTIONS.get(best_agent.handler, "manual-review")

    return AgentRoute(
        selected_agent=asdict(best_agent),
        score=round(best_score, 3),
        reasoning=best_reasons or ["fallback selection by best available match"],
        execution_mode=best_agent.handler,
        requires_human_approval=requires_human_approval,
        downstream_action=downstream_action,
        candidate_agents=sorted(candidates, key=lambda x: x["score"], reverse=True),
    )
