"""
auto_executor.py — Autonomous find + extract parameters + execute pipeline

This is the brain that makes OpenClaw able to run n8n workflows without
any human involvement. Given a plain-English intent, it:

  1. Finds the best matching workflow (semantic search)
  2. Extracts required parameters from the user's message
  3. Executes the workflow via n8n webhook
  4. Returns a structured result

This module is called by:
  - server.py /auto endpoint (for web UI and OpenClaw HTTP calls)
  - mcp_server.py run_automation tool (for MCP/native OpenClaw integration)
"""

import os
import re
import json
import httpx
import asyncio
from pathlib import Path
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

FLOWBRAIN_URL = os.getenv("FLOWBRAIN_URL", os.getenv("FLOW_FINDER_URL", "http://127.0.0.1:8001"))
OLLAMA_URL      = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.2")
N8N_BASE_URL    = os.getenv("N8N_BASE_URL", "http://localhost:5678")

# Confidence below this: don't auto-execute (raised from 0.35 to 0.85 for safety)
CONFIDENCE_THRESHOLD = float(os.getenv("FLOWBRAIN_MIN_AUTOEXEC_CONFIDENCE",
                             os.getenv("AUTO_CONFIDENCE_THRESHOLD", "0.85")))


@dataclass
class AutoResult:
    """The result of an autonomous execution attempt."""
    success:        bool
    intent:         str
    workflow_id:    str   = ""
    workflow_name:  str   = ""
    confidence:     float = 0.0
    params:         dict  = field(default_factory=dict)
    execution_result: dict = field(default_factory=dict)
    message:        str   = ""
    source_url:     str   = ""
    needs_webhook:  bool  = False


# ── Parameter extraction ──────────────────────────────────────────────────────

class ParameterExtractor:
    """
    Extracts structured parameters from natural language using:
    1. Fast regex patterns (always available, no LLM needed)
    2. Ollama LLM (if available, for complex extractions)
    """

    # ── Regex patterns ────────────────────────────────────────────────────────
    PATTERNS = {
        # Email
        "email_to":      r'\bto\s+([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
        "email_addr":    r'\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b',

        # Slack
        "slack_channel": r'#([a-zA-Z0-9_\-]+)',
        "slack_at":      r'(?<![\w.])@([a-zA-Z0-9_\-]+)\b',

        # URL
        "url":           r'https?://[^\s<>"{}|\\^`\[\]]+',

        # Dates and times
        "time":          r'\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))\b',
        "date_today":    r'\b(today)\b',
        "date_tomorrow": r'\b(tomorrow)\b',
        "date_monday":   r'\b((?:next\s+)?Monday)\b',
        "date_relative": r'\bin\s+(\d+\s+(?:minute|hour|day|week|month)s?)\b',

        # Numbers
        "count":         r'\b(\d+)\s+(?:row|item|record|message|email|file)s?\b',

        # Common subject/title patterns
        "subject_about": r'\babout[:\s]+([^,\.]+)',
        "title_called":  r'\b(?:called|named|titled)[:\s]+["\']?([^"\']+?)["\']?(?:\s|$)',
        "subject_re":    r'\bRe:\s*(.+)',
    }

    def extract(self, text: str, workflow_nodes: list[str] = None) -> dict:
        """
        Extract parameters from natural language text.
        Returns a dict of extracted key-value pairs.
        """
        params = {}
        nodes = workflow_nodes or []

        # Always extract universal params
        for key, pattern in self.PATTERNS.items():
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                params[key] = m.group(1).strip()

        # Consolidate email fields
        if "email_to" in params:
            params["to_email"] = params.pop("email_to")
            params.pop("email_addr", None)
        elif "email_addr" in params:
            params["to_email"] = params.pop("email_addr")

        # Add the full user message as context (always useful)
        params["user_message"] = text
        params["user_query"]   = text

        # Extract message content (everything after "saying", "message:", etc.)
        msg_match = re.search(
            r'(?:saying|message[:\s]+|body[:\s]+|content[:\s]+)["\']?(.+?)(?:["\']|$)',
            text, re.IGNORECASE | re.DOTALL
        )
        if msg_match:
            params["message"] = msg_match.group(1).strip()

        # Extract subject
        subj_match = re.search(
            r'subject[:\s]+["\']?(.+?)["\']?(?:\s+(?:and|with|to|body)|$)',
            text, re.IGNORECASE
        )
        if subj_match:
            params["subject"] = subj_match.group(1).strip()

        return params

    async def extract_with_llm(self, text: str, workflow_name: str, schema: dict) -> dict:
        """
        Use Ollama to extract parameters more accurately when regex isn't enough.
        Falls back to regex extraction if Ollama isn't available.
        """
        schema_str = json.dumps(schema.get("properties", {}), indent=2)

        prompt = f"""Extract the following parameters from the user's message for this automation workflow.

Workflow: {workflow_name}
Parameters needed:
{schema_str}

User's message: "{text}"

Return ONLY a valid JSON object with the extracted values.
If a parameter is not mentioned, omit it from the JSON.
Example output format: {{"to_email": "john@example.com", "subject": "Meeting notes", "message": "Here are the notes..."}}

JSON:"""

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
                )
                if r.status_code == 200:
                    response_text = r.json().get("response", "").strip()
                    # Extract JSON from response
                    json_match = re.search(r'\{[^{}]+\}', response_text, re.DOTALL)
                    if json_match:
                        extracted = json.loads(json_match.group())
                        # Merge with regex extraction (LLM takes priority)
                        regex_params = self.extract(text)
                        return {**regex_params, **extracted}
        except Exception:
            pass

        # Fallback to regex
        return self.extract(text)


# ── Webhook management ────────────────────────────────────────────────────────

def get_webhook_url(workflow_id: str) -> str | None:
    """Get the n8n webhook URL for a workflow from environment variables."""
    return (
        os.getenv(f"N8N_WEBHOOK_{workflow_id}") or
        os.getenv("N8N_DEFAULT_WEBHOOK")
    )


# ── Main autonomous executor ──────────────────────────────────────────────────

class AutoExecutor:
    """
    The autonomous execution engine.
    Given any natural language intent, finds and runs the right n8n workflow.
    """

    def __init__(self):
        self.extractor = ParameterExtractor()

    async def run(self, intent: str, extra_params: dict = None) -> AutoResult:
        """
        Full pipeline: search → extract → execute → return result.

        Args:
            intent:       What the user wants to do, in plain English
            extra_params: Optional params to pass directly (skip extraction for these)

        Returns:
            AutoResult with success status and details
        """
        if not intent or not intent.strip():
            return AutoResult(success=False, intent=intent, message="Intent cannot be empty.")

        extra_params = extra_params or {}

        # ── Step 1: Find the best workflow ─────────────────────────────────
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"{FLOWBRAIN_URL}/search",
                    json={"query": intent, "top_k": 3}
                )
                r.raise_for_status()
                results = r.json().get("results", [])
        except Exception as e:
            return AutoResult(
                success=False, intent=intent,
                message=f"Could not reach FlowBrain at {FLOWBRAIN_URL}. Is it running? Error: {e}"
            )

        if not results:
            return AutoResult(
                success=False, intent=intent,
                message="No matching automation found. Try rephrasing or use more specific service names."
            )

        best = results[0]
        confidence = best.get("confidence", 0.0)

        if confidence < CONFIDENCE_THRESHOLD:
            # Show what we found but don't auto-execute low-confidence matches
            return AutoResult(
                success=False,
                intent=intent,
                workflow_id=best["workflow_id"],
                workflow_name=best["name"],
                confidence=confidence,
                source_url=best.get("source_url", ""),
                message=(
                    f"Found a potential match ({int(confidence*100)}% confidence): "
                    f"**{best['name']}** — but I'm not confident enough to run it automatically. "
                    f"Try being more specific about what you want to do."
                )
            )

        wf_id    = best["workflow_id"]
        wf_name  = best["name"]
        wf_nodes = best.get("nodes", [])

        # ── Step 2: Extract parameters ─────────────────────────────────────
        # Try LLM extraction first, fall back to regex
        schema = _build_quick_schema(wf_name, wf_nodes)

        # Check if Ollama is available
        ollama_available = await _check_ollama()

        if ollama_available:
            params = await self.extractor.extract_with_llm(intent, wf_name, schema)
        else:
            params = self.extractor.extract(intent, wf_nodes)

        # Merge with any explicitly provided params (they take priority)
        params.update(extra_params)

        # ── Step 3: Execute ────────────────────────────────────────────────
        webhook_url = get_webhook_url(wf_id)

        if not webhook_url:
            return AutoResult(
                success=True,   # "success" in the sense of finding the right workflow
                intent=intent,
                workflow_id=wf_id,
                workflow_name=wf_name,
                confidence=confidence,
                params=params,
                source_url=best.get("source_url", ""),
                needs_webhook=True,
                message=(
                    f"✅ Found the right automation: **{wf_name}** ({int(confidence*100)}% match)\n\n"
                    f"Parameters extracted:\n{_format_params(params)}\n\n"
                    f"⚠️ To execute this, add to your `.env` file:\n"
                    f"`N8N_WEBHOOK_{wf_id}=<your-n8n-webhook-url>`\n\n"
                    f"Then activate the workflow in n8n and get its webhook URL.\n"
                    f"📖 View workflow: {best.get('source_url', '')}"
                )
            )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(webhook_url, json=params)
                resp.raise_for_status()
                exec_result = {"status_code": resp.status_code, "response": resp.text[:2000]}
        except httpx.TimeoutException:
            exec_result = {"error": "Webhook timed out (30s)"}
        except httpx.HTTPStatusError as e:
            exec_result = {"error": f"Webhook returned HTTP {e.response.status_code}"}
        except Exception as e:
            exec_result = {"error": str(e)}

        success = "error" not in exec_result

        message = (
            f"✅ Executed: **{wf_name}**\n"
            f"Confidence: {int(confidence*100)}%\n"
            f"Parameters: {_format_params(params)}\n\n"
            f"Response: {exec_result.get('response', exec_result.get('error', 'Done.'))}"
            if success else
            f"❌ Execution failed: {exec_result.get('error', 'Unknown error')}\n"
            f"Workflow: {wf_name}"
        )

        return AutoResult(
            success=success,
            intent=intent,
            workflow_id=wf_id,
            workflow_name=wf_name,
            confidence=confidence,
            params=params,
            execution_result=exec_result,
            source_url=best.get("source_url", ""),
            message=message,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_quick_schema(name: str, nodes: list) -> dict:
    """Quick parameter schema from workflow name and nodes."""
    props = {"user_query": {"type": "string"}}
    name_lower = name.lower()

    if any(n in nodes for n in ["Gmail", "Email", "Outlook", "SMTP"]):
        props.update({
            "to_email": {"type": "string"},
            "subject":  {"type": "string"},
            "message":  {"type": "string"},
        })
    if "Slack" in nodes:
        props.update({"slack_channel": {"type": "string"}, "message": {"type": "string"}})
    if "Notion" in nodes:
        props.update({"page_title": {"type": "string"}, "page_content": {"type": "string"}})
    if any(n in nodes for n in ["Twitter", "X (Twitter)"]):
        props["tweet_text"] = {"type": "string"}
    if "Telegram" in nodes:
        props.update({"message": {"type": "string"}, "chat_id": {"type": "string"}})
    if "Google Sheets" in nodes:
        props.update({"spreadsheet_id": {"type": "string"}, "data": {"type": "string"}})

    return {"type": "object", "properties": props}


async def _check_ollama() -> bool:
    """Check if Ollama is running locally."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def _format_params(params: dict) -> str:
    """Format extracted params as a readable string, omitting internal fields."""
    SKIP = {"user_message", "user_query"}
    lines = []
    for k, v in params.items():
        if k not in SKIP and v:
            val_str = str(v)[:80] + ("..." if len(str(v)) > 80 else "")
            lines.append(f"  • {k}: {val_str}")
    return "\n".join(lines) if lines else "  (no specific params extracted)"


# ── Singleton ─────────────────────────────────────────────────────────────────

_executor: AutoExecutor | None = None

def get_executor() -> AutoExecutor:
    global _executor
    if _executor is None:
        _executor = AutoExecutor()
    return _executor


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    intent = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else \
        "Send an email to test@example.com with subject Hello and body This is a test message"

    print(f'\n🤖 Auto-executing: "{intent}"\n')

    async def main():
        executor = AutoExecutor()
        result   = await executor.run(intent)
        print(result.message)
        if result.params:
            print(f"\nExtracted params: {json.dumps(result.params, indent=2)}")

    asyncio.run(main())
