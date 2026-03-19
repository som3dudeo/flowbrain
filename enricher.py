"""
enricher.py — Step 2b (optional but recommended): Enrich workflow descriptions

Many workflows in the n8n library have empty or very short descriptions.
This script auto-generates quality descriptions using:
  1. Ollama (local LLM, completely free) — best quality
  2. OpenAI GPT-4o-mini (if OPENAI_API_KEY is set) — excellent quality, ~$0.01 total
  3. Rule-based generation (always available, no AI needed) — good quality

Run:  python enricher.py              (uses best available method)
      python enricher.py --method rule (force rule-based, no LLM)
      python enricher.py --method ollama
      python enricher.py --method openai

Run this AFTER harvester.py and BEFORE indexer.py for best search results.
"""

import json
import time
import argparse
import os
import re
from pathlib import Path
from tqdm import tqdm

WORKFLOWS_DIR = Path("./data/workflows")
OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL  = os.getenv("OLLAMA_MODEL", "llama3.2")
MIN_DESC_LEN  = 40   # descriptions shorter than this get enriched


# ── Method detection ──────────────────────────────────────────────────────────

def detect_best_method() -> str:
    """Auto-detect the best enrichment method available."""
    # Try Ollama first (local, free)
    try:
        import requests
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            if models:
                print(f"  ✓ Ollama detected ({len(models)} models available)")
                return "ollama"
    except Exception:
        pass

    # Try OpenAI
    if os.getenv("OPENAI_API_KEY"):
        print("  ✓ OpenAI API key detected")
        return "openai"

    # Fallback: rule-based
    print("  ✓ Using rule-based enrichment (no LLM needed)")
    return "rule"


# ── Enrichment methods ────────────────────────────────────────────────────────

def enrich_with_ollama(name: str, nodes: list[str], tags: list[str]) -> str:
    """Generate description using a local Ollama LLM."""
    import requests

    nodes_str = ", ".join(nodes[:6]) if nodes else "various services"
    prompt = (
        f"Write a clear, helpful 2-sentence description for an n8n automation workflow.\n"
        f"Workflow name: {name}\n"
        f"Integrations used: {nodes_str}\n\n"
        f"The description should explain: (1) what triggers the workflow, "
        f"(2) what it does. Be specific and practical. No bullet points. Just 2 sentences."
    )

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json().get("response", "").strip()
    except Exception:
        pass
    return ""


def enrich_with_openai(name: str, nodes: list[str], tags: list[str], client) -> str:
    """Generate description using OpenAI."""
    nodes_str = ", ".join(nodes[:6]) if nodes else "various services"
    prompt = (
        f"Write a clear, helpful 2-sentence description for an n8n automation workflow.\n"
        f"Workflow name: {name}\n"
        f"Integrations: {nodes_str}\n\n"
        f"Explain: (1) what triggers it, (2) what it does. Be specific. No bullets. 2 sentences max."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ""


def enrich_with_rules(name: str, nodes: list[str], categories: list[str]) -> str:
    """
    Generate a description purely from workflow name and node types.
    No LLM needed — works offline.
    """
    name_clean = name.strip()

    # Extract key service names from nodes (skip generic nodes)
    SKIP_NODES = {
        "Webhook", "Manual Trigger", "Schedule Trigger", "Set", "If",
        "Switch", "Merge", "Code", "Function", "Http Request", "Json",
        "No Op", "Start", "Error Trigger", "Execute Workflow",
    }
    services = [n for n in nodes if n not in SKIP_NODES]

    # Detect trigger pattern from name
    trigger = _detect_trigger(name_clean, nodes)
    action  = _detect_action(name_clean, nodes)

    if trigger and action:
        desc = f"{trigger} {action}"
    elif services and len(services) >= 2:
        desc = (
            f"Automates the connection between {services[0]} and {services[1]}. "
            f"This workflow handles data flow and synchronization between the two services automatically."
        )
    elif services:
        desc = (
            f"An n8n automation workflow using {services[0]}. "
            f"This workflow streamlines tasks and reduces manual effort for {services[0]}-related processes."
        )
    else:
        # Last resort: generate from the name itself
        desc = (
            f"Automates the process described in: {name_clean}. "
            f"This n8n workflow reduces manual effort and keeps your systems in sync automatically."
        )

    return desc


def _detect_trigger(name: str, nodes: list[str]) -> str:
    """Guess the trigger sentence from workflow name patterns."""
    name_lower = name.lower()

    patterns = [
        (r"when (.+?) (?:is |are )?submitted",   "When a {0} is submitted,"),
        (r"when (.+?) (?:is |are )?created",      "When a new {0} is created,"),
        (r"when (.+?) (?:is |are )?received",     "When a {0} is received,"),
        (r"when (?:new )?(.+?) (?:is |are )?added", "When a new {0} is added,"),
        (r"on new (.+)",                           "On a new {0},"),
        (r"from (.+?) to",                         "When triggered from {0},"),
        (r"every (.+?) (?:send|post|create|update|sync)", "Every {0},"),
        (r"schedule[d]? (.+)",                     "On a scheduled basis,"),
    ]

    for pattern, template in patterns:
        m = re.search(pattern, name_lower)
        if m:
            subject = m.group(1).strip().title()
            return template.format(subject)

    # Check nodes for known trigger types
    trigger_node_map = {
        "Webhook":            "When triggered via webhook,",
        "Schedule Trigger":   "On a scheduled interval,",
        "Gmail Trigger":      "When a new Gmail email arrives,",
        "Slack Trigger":      "When a Slack event occurs,",
        "Github Trigger":     "When a GitHub event is detected,",
        "Typeform Trigger":   "When a Typeform response is submitted,",
        "Airtable Trigger":   "When an Airtable record is updated,",
    }
    for node, trigger in trigger_node_map.items():
        if node in nodes:
            return trigger

    return "When triggered,"


def _detect_action(name: str, nodes: list[str]) -> str:
    """Guess the action sentence from workflow name patterns."""
    name_lower = name.lower()

    if "send" in name_lower and "email" in name_lower:
        return "this workflow sends an automated email notification."
    if "send" in name_lower and "slack" in name_lower:
        return "this workflow sends a Slack message to the configured channel."
    if "create" in name_lower and ("ticket" in name_lower or "issue" in name_lower):
        return "this workflow creates a new support ticket or issue automatically."
    if "save" in name_lower or "store" in name_lower:
        return "this workflow saves and stores the data to the configured destination."
    if "sync" in name_lower:
        return "this workflow synchronizes data between the connected services."
    if "notify" in name_lower:
        return "this workflow sends a notification to the configured platform."
    if "backup" in name_lower:
        return "this workflow creates an automated backup of the specified data."
    if "summarize" in name_lower or "summary" in name_lower:
        return "this workflow generates a summary using AI and delivers it to the destination."

    # Check destination nodes
    dest_map = {
        "Slack":        "this workflow posts a message to Slack.",
        "Gmail":        "this workflow sends an email via Gmail.",
        "Google Sheets": "this workflow updates a Google Sheet with the data.",
        "Airtable":     "this workflow creates or updates an Airtable record.",
        "Notion":       "this workflow creates or updates a Notion page.",
        "Telegram":     "this workflow sends a Telegram message.",
        "Discord":      "this workflow posts a message to Discord.",
        "Trello":       "this workflow creates or updates a Trello card.",
        "Jira":         "this workflow creates or updates a Jira issue.",
        "HubSpot":      "this workflow updates a HubSpot contact or deal.",
    }
    for node, action in dest_map.items():
        if node in nodes:
            return action

    return "this workflow automates the process and handles the data accordingly."


# ── Main enrichment pipeline ──────────────────────────────────────────────────

def enrich_all(method: str = "auto", force: bool = False) -> int:
    """
    Enrich descriptions for all workflows that need it.
    Returns the number of workflows enriched.
    """
    if not WORKFLOWS_DIR.exists() or not any(WORKFLOWS_DIR.glob("*.json")):
        print("❌ No workflows found. Run `python harvester.py` first.")
        return 0

    all_files = sorted(WORKFLOWS_DIR.glob("*.json"))

    # Find files that need enrichment
    needs_enrichment = []
    for f in all_files:
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
            desc = wf.get("description", "").strip()
            if force or len(desc) < MIN_DESC_LEN:
                needs_enrichment.append(f)
        except Exception:
            continue

    if not needs_enrichment:
        print(f"✅ All {len(all_files)} workflows already have descriptions. Nothing to enrich.")
        print("   Use --force to re-enrich everything.")
        return 0

    print(f"\n✍️  n8n Workflow Description Enricher")
    print(f"   {len(needs_enrichment)} workflows need descriptions ({len(all_files)} total)\n")

    if method == "auto":
        method = detect_best_method()

    print(f"   Method: {method.upper()}\n")

    # Set up LLM client if needed
    openai_client = None
    if method == "openai":
        try:
            from openai import OpenAI
            openai_client = OpenAI()
        except ImportError:
            print("  ⚠️  openai package not installed. Falling back to rule-based.")
            method = "rule"

    enriched_count = 0

    for filepath in tqdm(needs_enrichment, unit="workflow"):
        try:
            wf = json.loads(filepath.read_text(encoding="utf-8"))

            name       = wf.get("name", "").strip()
            nodes      = wf.get("nodes", [])
            tags       = wf.get("tags", [])
            categories = wf.get("categories", [])

            if not name:
                continue

            if method == "ollama":
                new_desc = enrich_with_ollama(name, nodes, tags)
                if not new_desc:  # fallback if Ollama fails
                    new_desc = enrich_with_rules(name, nodes, categories)

            elif method == "openai" and openai_client:
                new_desc = enrich_with_openai(name, nodes, tags, openai_client)
                if not new_desc:
                    new_desc = enrich_with_rules(name, nodes, categories)
                time.sleep(0.05)  # small delay for rate limiting

            else:  # rule-based
                new_desc = enrich_with_rules(name, nodes, categories)

            if new_desc and len(new_desc) > MIN_DESC_LEN:
                wf["description"] = new_desc
                wf["description_enriched"] = True
                filepath.write_text(json.dumps(wf, indent=2, ensure_ascii=False), encoding="utf-8")
                enriched_count += 1

        except Exception:
            continue

    print(f"\n✅ Enriched {enriched_count} workflow descriptions!")
    print(f"   Now re-run `python indexer.py --rebuild` to update the search index.\n")
    return enriched_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich n8n workflow descriptions")
    parser.add_argument("--method", choices=["auto", "ollama", "openai", "rule"],
                        default="auto", help="Enrichment method (default: auto-detect)")
    parser.add_argument("--force", action="store_true",
                        help="Re-enrich even workflows that already have descriptions")
    args = parser.parse_args()
    enrich_all(method=args.method, force=args.force)
