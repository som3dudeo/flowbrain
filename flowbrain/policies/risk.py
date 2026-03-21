"""Risk classification for workflows based on their node types and actions."""

from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


# Canonicalised node names are lowercase.
HIGH_RISK_NODES = {
    "gmail", "outlook", "email", "emailsend", "smtp",      # sends emails
    "twitter", "x (twitter)", "linkedin",                    # public posting
    "slack", "discord", "telegram", "whatsapp",            # messaging
    "twilio", "microsoftteams",                               # SMS / chat
}

MEDIUM_RISK_NODES = {
    "notion", "airtable", "google sheets", "googlesheets",
    "jira", "linear", "trello", "asana",
    "github", "gitlab",
    "hubspot", "salesforce",
    "google drive", "googledrive", "dropbox", "s3",
    "supabase", "postgres", "mysql", "mongodb",
}

LOW_RISK_NODES = {
    "webhook", "manual trigger", "schedule trigger",
    "http request", "httprequest", "rss feed",
    "set", "if", "switch", "merge", "code", "function",
    "json", "xml", "csv", "no op", "start",
}

INTERNAL_NODES = {
    "webhook", "manual trigger", "schedule trigger", "set", "if",
    "switch", "merge", "code", "function", "json", "xml", "csv",
    "no op", "start", "error trigger", "execute workflow",
    "http request", "httprequest",
}


def _normalise_nodes(nodes: list[str]) -> set[str]:
    return {str(n).strip().lower() for n in nodes if str(n).strip()}


def classify_risk(nodes: list[str], workflow_name: str = "") -> RiskLevel:
    """
    Classify the risk level of a workflow based on its nodes.

    HIGH: sends external messages (email, Slack, social media)
    MEDIUM: creates/updates data in external systems
    LOW: read-only or internal operations
    UNKNOWN: can't determine
    """
    if not nodes:
        return RiskLevel.UNKNOWN

    node_set = _normalise_nodes(nodes)

    if node_set & HIGH_RISK_NODES:
        return RiskLevel.HIGH

    if node_set & MEDIUM_RISK_NODES:
        return RiskLevel.MEDIUM

    if node_set and node_set <= LOW_RISK_NODES:
        return RiskLevel.LOW

    if node_set & LOW_RISK_NODES:
        return RiskLevel.LOW

    return RiskLevel.UNKNOWN


def get_affected_systems(nodes: list[str]) -> list[str]:
    """Return the external systems a workflow will interact with."""
    return [n for n in nodes if str(n).strip().lower() not in INTERNAL_NODES]
