"""Confidence gating — decides whether to auto-execute or require preview."""

from flowbrain.config import get_config


def should_auto_execute(confidence: float, risk_level: str = "unknown", auto_execute_requested: bool = False) -> bool:
    """
    Decide if an automation should execute automatically.

    Rules:
    - HIGH risk: NEVER auto-execute regardless of confidence
    - Must be above min_autoexec_confidence
    - auto_execute must be explicitly requested
    - MEDIUM risk: only if confidence >= 0.90
    """
    cfg = get_config()
    rl = risk_level.lower() if isinstance(risk_level, str) else str(risk_level).lower()

    if rl == "high":
        return False

    if not auto_execute_requested:
        return False

    if confidence < cfg.min_autoexec_confidence:
        return False

    if rl == "medium" and confidence < 0.90:
        return False

    return True


def should_preview(confidence: float) -> bool:
    """Decide if results are confident enough to even offer a preview."""
    cfg = get_config()
    return confidence >= cfg.min_preview_confidence
