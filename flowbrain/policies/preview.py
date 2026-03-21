"""Preview mode — shows what would happen without executing."""

from dataclasses import dataclass, field
from flowbrain.policies.risk import classify_risk, get_affected_systems, RiskLevel
from flowbrain.policies.confidence import should_auto_execute, should_preview


@dataclass
class PreviewResult:
    """What the user sees before deciding to execute."""
    intent: str
    normalized_intent: str = ""
    workflow_id: str = ""
    workflow_name: str = ""
    confidence: float = 0.0
    confidence_pct: str = ""
    risk_level: str = "unknown"
    systems_affected: list[str] = field(default_factory=list)
    params_extracted: dict = field(default_factory=dict)
    missing_params: list[str] = field(default_factory=list)
    would_auto_execute: bool = False
    execution_blocked: bool = False
    block_reason: str = ""
    action_summary: str = ""
    alternatives: list[dict] = field(default_factory=list)
    source_url: str = ""

    @property
    def is_safe_to_execute(self) -> bool:
        return not self.execution_blocked and self.confidence > 0.0


def build_preview(
    intent: str,
    workflow_id: str,
    workflow_name: str,
    confidence: float,
    nodes: list[str],
    params: dict,
    auto_execute_requested: bool = False,
    alternatives: list[dict] | None = None,
    source_url: str = "",
) -> PreviewResult:
    """Build a rich preview of what would happen if executed."""

    risk = classify_risk(nodes, workflow_name)
    systems = get_affected_systems(nodes)
    can_auto = should_auto_execute(confidence, risk.value, auto_execute_requested)
    can_preview = should_preview(confidence)

    # Determine if execution should be blocked
    blocked = False
    block_reason = ""
    if not can_preview:
        blocked = True
        block_reason = f"Confidence too low ({confidence:.0%}) for any action"
    elif risk == RiskLevel.HIGH and not auto_execute_requested:
        blocked = True
        block_reason = f"High-risk action ({', '.join(systems)}) requires explicit approval"

    # Build action summary
    if systems:
        action_summary = f"Will interact with: {', '.join(systems)}"
    else:
        action_summary = "Internal workflow (no external side effects detected)"

    # Identify potentially missing params
    missing = []
    skip_keys = {"user_message", "user_query"}
    extracted = {k: v for k, v in params.items() if k not in skip_keys and v}
    if not extracted:
        missing.append("No specific parameters extracted from intent")

    return PreviewResult(
        intent=intent,
        normalized_intent=intent.strip().lower(),
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        confidence=confidence,
        confidence_pct=f"{int(confidence * 100)}%",
        risk_level=risk.value,
        systems_affected=systems,
        params_extracted=params,
        missing_params=missing,
        would_auto_execute=can_auto,
        execution_blocked=blocked,
        block_reason=block_reason,
        action_summary=action_summary,
        alternatives=alternatives or [],
        source_url=source_url,
    )
