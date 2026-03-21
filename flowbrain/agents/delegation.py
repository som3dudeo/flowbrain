"""
Delegation plans for non-workflow agent types.

When /manage routes to an agent that isn't the workflow-automation handler,
we can't execute directly — but we CAN return a structured, actionable
delegation plan that tells the caller exactly what to do next.

For OpenClaw: the plan includes the exact tool/command to invoke.
For API callers: the plan includes structured metadata for their own dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from flowbrain.agents.router import AgentRoute


@dataclass
class DelegationPlan:
    """Structured plan for a non-workflow agent delegation."""
    agent_id: str
    agent_name: str
    handler: str
    intent: str
    execution_ready: bool                    # True = caller can act on this plan
    protocol: str = ""                       # "openclaw-skill" | "http-callback" | "manual"
    instructions: str = ""                   # Human-readable instruction for the caller
    tool_call: dict = field(default_factory=dict)  # Machine-readable next action
    requires_human_approval: bool = True
    fallback_message: str = ""               # What to show the user if delegation fails

    def to_dict(self) -> dict:
        return asdict(self)


# ── Delegation builders per handler type ─────────────────────────────────────

def _build_coding_plan(intent: str, route: AgentRoute) -> DelegationPlan:
    return DelegationPlan(
        agent_id=route.selected_agent["id"],
        agent_name=route.selected_agent["name"],
        handler="acp",
        intent=intent,
        execution_ready=True,
        protocol="openclaw-skill",
        instructions=(
            f"This is a coding task. Delegate to a coding agent or IDE tool.\n"
            f"Intent: {intent}\n"
            f"Suggested action: Open a coding session and execute the task directly."
        ),
        tool_call={
            "type": "coding-session",
            "action": "spawn",
            "payload": {
                "intent": intent,
                "mode": "supervised",
                "language_hints": _extract_language_hints(intent),
            },
        },
        requires_human_approval=True,
        fallback_message=(
            f"I've identified this as a coding task. "
            f"Please use your preferred IDE or coding agent to: {intent}"
        ),
    )


def _build_research_plan(intent: str, route: AgentRoute) -> DelegationPlan:
    return DelegationPlan(
        agent_id=route.selected_agent["id"],
        agent_name=route.selected_agent["name"],
        handler="analysis",
        intent=intent,
        execution_ready=True,
        protocol="internal",
        instructions=(
            f"This is a research/analysis task.\n"
            f"Intent: {intent}\n"
            f"Suggested action: Gather information and produce a summary."
        ),
        tool_call={
            "type": "research-task",
            "action": "analyze",
            "payload": {
                "intent": intent,
                "output_format": "summary",
            },
        },
        requires_human_approval=False,
        fallback_message=(
            f"I've identified this as a research task: {intent}. "
            f"I can help you analyze this — please provide more context or data sources."
        ),
    )


def _build_openclaw_plan(intent: str, route: AgentRoute) -> DelegationPlan:
    return DelegationPlan(
        agent_id=route.selected_agent["id"],
        agent_name=route.selected_agent["name"],
        handler="openclaw",
        intent=intent,
        execution_ready=True,
        protocol="openclaw-native",
        instructions=(
            f"This is an orchestration task for OpenClaw.\n"
            f"Intent: {intent}\n"
            f"Suggested action: Use OpenClaw's native tools (cron, sessions, reminders)."
        ),
        tool_call={
            "type": "openclaw-operation",
            "action": "orchestrate",
            "payload": {
                "intent": intent,
                "capabilities_needed": route.selected_agent.get("capabilities", []),
            },
        },
        requires_human_approval=True,
        fallback_message=(
            f"This requires OpenClaw orchestration: {intent}. "
            f"Use OpenClaw directly for reminders, cron jobs, and multi-agent sessions."
        ),
    )


def build_delegation_plan(intent: str, route: AgentRoute) -> DelegationPlan:
    """Build a structured delegation plan for a non-workflow agent route."""
    handler = route.execution_mode

    builders = {
        "acp": _build_coding_plan,
        "analysis": _build_research_plan,
        "openclaw": _build_openclaw_plan,
    }

    builder = builders.get(handler)
    if builder:
        return builder(intent, route)

    # Unknown handler — generic fallback
    return DelegationPlan(
        agent_id=route.selected_agent["id"],
        agent_name=route.selected_agent["name"],
        handler=handler,
        intent=intent,
        execution_ready=False,
        protocol="manual",
        instructions=f"No automated handler for '{handler}'. Manual action required.",
        requires_human_approval=True,
        fallback_message=f"I routed this to {route.selected_agent['name']} but cannot execute automatically.",
    )


def _extract_language_hints(intent: str) -> list[str]:
    """Extract programming language hints from an intent string."""
    text = intent.lower()
    hints = []
    languages = {
        "python": ["python", "py", "pip", "django", "flask", "fastapi"],
        "javascript": ["javascript", "js", "node", "npm", "react", "vue", "next"],
        "typescript": ["typescript", "ts", "tsx"],
        "rust": ["rust", "cargo"],
        "go": ["golang", "go module"],
        "shell": ["bash", "shell", "script", "sh"],
    }
    for lang, keywords in languages.items():
        if any(kw in text for kw in keywords):
            hints.append(lang)
    return hints
