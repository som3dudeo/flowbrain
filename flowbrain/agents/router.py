"""Task-to-agent routing and execution planning."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from flowbrain.agents.registry import AgentProfile, get_registry


def _word_match(keyword: str, text: str) -> bool:
    """Check if keyword appears as a whole word in text (not as a substring)."""
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text))


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

    # Track which words already matched to avoid double-counting
    matched_words: set[str] = set()

    for keyword in agent.keywords:
        kw = keyword.lower()
        if _word_match(kw, text):
            score += 0.18
            reasons.append(f"matched keyword '{keyword}'")
            matched_words.add(kw)

    for capability in agent.capabilities:
        cap = capability.lower()
        if _word_match(cap, text) and cap not in matched_words:
            score += 0.12
            reasons.append(f"matched capability '{capability}'")
            matched_words.add(cap)

    for keyword in _KEYWORD_BONUS.get(agent.handler, []):
        if _word_match(keyword, text) and keyword not in matched_words:
            score += 0.08
            reasons.append(f"handler '{agent.handler}' fits '{keyword}'")

    if agent.handler == "workflow" and any(_word_match(x, text) for x in ["workflow", "n8n", "automation"]):
        score += 0.15
        reasons.append("workflow-oriented request")
    if agent.handler == "acp" and any(_word_match(x, text) for x in ["repo", "fix", "implement", "debug"]):
        score += 0.15
        reasons.append("coding-oriented request")
    if agent.handler == "openclaw" and any(_word_match(x, text) for x in ["agent manager", "delegate", "orchestrate", "session"]):
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

    if best_agent is None:
        raise ValueError("No agents registered")

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
