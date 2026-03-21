"""
mcp_server.py — MCP (Model Context Protocol) Server for n8n Workflows

This is the key file that turns n8n workflows into OpenClaw skills.

Instead of a human searching for workflows, OpenClaw's AI brain calls this
MCP server, which exposes every indexed n8n workflow as a callable tool.
OpenClaw sees thousands of "skills" it can invoke autonomously.

How it works:
  1. On startup, loads the top N workflows from the vector index
  2. Exposes each as an MCP tool with a name, description, and parameter schema
  3. Also exposes a dynamic "find_and_run" tool that does semantic search + execution
  4. When a tool is called, hits the corresponding n8n webhook with the params
  5. Returns the result back to OpenClaw

Running as MCP server (for OpenClaw):
  python mcp_server.py

OpenClaw config (add to your OpenClaw settings):
  {
    "mcpServers": {
      "n8n-workflows": {
        "command": "python3",
        "args": ["~/Documents/flowbrain/mcp_server.py"],
        "env": {}
      }
    }
  }
"""

import os
import sys
import json
import asyncio
import httpx
from pathlib import Path
from typing import Any

# ── MCP SDK ───────────────────────────────────────────────────────────────────
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

# ── Load env ──────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

N8N_BASE_URL = os.getenv("N8N_BASE_URL", "http://localhost:5678")
FLOW_FINDER_URL = os.getenv("FLOW_FINDER_URL", "http://localhost:8000")

# How many workflows to pre-load as dedicated MCP tools
# The rest are still accessible via the universal "run_automation" tool
TOP_TOOLS = int(os.getenv("MCP_TOP_TOOLS", "50"))


# ── Workflow registry ─────────────────────────────────────────────────────────

def load_top_workflows(n: int = TOP_TOOLS) -> list[dict]:
    """Load the top N most-viewed workflows to expose as dedicated tools."""
    workflows_dir = Path("./data/workflows")
    if not workflows_dir.exists():
        return []

    workflows = []
    for f in workflows_dir.glob("*.json"):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
            workflows.append(wf)
        except Exception:
            continue

    # Sort by views (most popular first), then take top N with good descriptions
    workflows_with_desc = [w for w in workflows if len(w.get("description", "")) > 30]
    workflows_with_desc.sort(key=lambda w: w.get("views", 0), reverse=True)
    return workflows_with_desc[:n]


def workflow_to_tool_name(wf: dict) -> str:
    """Convert a workflow name to a valid MCP tool name (snake_case, no spaces)."""
    name = wf.get("name", f"workflow_{wf.get('id', 'unknown')}")
    # Lowercase, replace spaces/special chars with underscores
    import re
    clean = re.sub(r'[^a-zA-Z0-9\s]', '', name)
    clean = re.sub(r'\s+', '_', clean.strip()).lower()
    clean = re.sub(r'_+', '_', clean)[:60]  # max 60 chars
    return clean or f"workflow_{wf.get('id', 'unknown')}"


def build_tool_schema(wf: dict) -> dict:
    """
    Build a JSON schema for the workflow's parameters.
    Uses the node types to guess what parameters are needed.
    """
    nodes = wf.get("nodes", [])
    name  = wf.get("name", "")
    name_lower = name.lower()

    properties = {
        "user_query": {
            "type": "string",
            "description": "What you want to do — provide as much detail as possible (names, emails, dates, channels, etc.)"
        }
    }

    # Add commonly needed parameters based on workflow content
    if any(n in nodes for n in ["Gmail", "Outlook", "Email"]):
        if "send" in name_lower or "email" in name_lower:
            properties["to_email"] = {"type": "string", "description": "Recipient email address"}
            properties["subject"] = {"type": "string", "description": "Email subject line"}
            properties["body"] = {"type": "string", "description": "Email body content"}

    if "Slack" in nodes and ("send" in name_lower or "post" in name_lower or "notify" in name_lower):
        properties["slack_channel"] = {"type": "string", "description": "Slack channel name (e.g. #general)"}
        properties["message"] = {"type": "string", "description": "Message text to send"}

    if "Google Sheets" in nodes and ("add" in name_lower or "append" in name_lower or "update" in name_lower):
        properties["spreadsheet_id"] = {"type": "string", "description": "Google Sheets spreadsheet ID or URL"}
        properties["data"] = {"type": "string", "description": "Data to add (describe what to add)"}

    if "Notion" in nodes:
        properties["page_content"] = {"type": "string", "description": "Content to add to Notion"}
        properties["page_title"] = {"type": "string", "description": "Title of the Notion page"}

    if "Twitter" in nodes or "X (Twitter)" in nodes:
        properties["tweet_text"] = {"type": "string", "description": "Text content for the tweet (max 280 chars)"}

    if "Telegram" in nodes:
        properties["message"] = {"type": "string", "description": "Message to send via Telegram"}
        properties["chat_id"] = {"type": "string", "description": "Telegram chat ID (optional, uses default if not set)"}

    if any(n in nodes for n in ["Jira", "Linear", "Trello", "Asana"]):
        properties["task_title"] = {"type": "string", "description": "Title or name of the task/ticket"}
        properties["task_description"] = {"type": "string", "description": "Description of the task"}

    return {
        "type": "object",
        "properties": properties,
        "required": ["user_query"]
    }


async def call_flow_finder(query: str, top_k: int = 1) -> list[dict]:
    """Search Flow Finder for the best matching workflow."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{FLOW_FINDER_URL}/search",
                json={"query": query, "top_k": top_k}
            )
            r.raise_for_status()
            return r.json().get("results", [])
    except Exception:
        return []


async def execute_workflow(workflow_id: str, query: str, params: dict) -> dict:
    """Execute a workflow via the Flow Finder /execute endpoint."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{FLOW_FINDER_URL}/execute",
                json={"workflow_id": workflow_id, "query": query, "params": params}
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── MCP Server ────────────────────────────────────────────────────────────────

def run_mcp_server():
    """Run the MCP server that exposes n8n workflows as tools."""
    if not MCP_AVAILABLE:
        print("ERROR: MCP SDK not installed.", file=sys.stderr)
        print("Install with: pip install mcp", file=sys.stderr)
        sys.exit(1)

    server = Server("n8n-workflows")
    top_workflows = load_top_workflows(TOP_TOOLS)

    print(f"[n8n MCP] Loaded {len(top_workflows)} workflows as tools", file=sys.stderr)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools = []

        # ── Tool 1: Universal dynamic skill runner ────────────────────────────
        tools.append(types.Tool(
            name="run_automation",
            description=(
                "Run any automation task using thousands of available n8n workflows. "
                "Use this when you need to: send emails, post to Slack, update Notion, "
                "create Jira tickets, post tweets, add rows to Google Sheets, send WhatsApp "
                "messages, trigger webhooks, or automate any other task. "
                "Describe what you want to do and this tool finds and executes the best workflow. "
                "ALWAYS try this tool before saying you cannot perform an action."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": (
                            "A clear description of what to do. Include specific details: "
                            "names, email addresses, channel names, dates, content to send. "
                            "Example: 'Send an email to john@example.com with subject Meeting Notes "
                            "and body: Here are the notes from today...'"
                        )
                    },
                    "params": {
                        "type": "object",
                        "description": "Optional: specific parameters to pass to the workflow (email addresses, channel names, etc.)",
                        "additionalProperties": True
                    }
                },
                "required": ["task"]
            }
        ))

        # ── Tool 2: List available capabilities ───────────────────────────────
        tools.append(types.Tool(
            name="list_automations",
            description=(
                "Search and list available automation workflows. Use this to discover "
                "what automations are available before running one, or to show the user "
                "what n8n skills are available."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What kind of automation to search for (e.g. 'Slack notifications', 'email sending', 'Notion updates')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many results to return (default 5)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        ))

        # ── Tools 3+: Individual top-N workflow tools ─────────────────────────
        for wf in top_workflows:
            tool_name   = workflow_to_tool_name(wf)
            description = wf.get("description", "")
            nodes_str   = ", ".join(wf.get("nodes", [])[:6])
            full_desc   = f"{description}"
            if nodes_str:
                full_desc += f" (Uses: {nodes_str})"
            if wf.get("source_url"):
                full_desc += f" — {wf['source_url']}"

            tools.append(types.Tool(
                name=tool_name,
                description=full_desc[:1000],
                inputSchema=build_tool_schema(wf)
            ))

        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

        # ── Universal runner ──────────────────────────────────────────────────
        if name == "run_automation":
            task   = arguments.get("task", "")
            params = arguments.get("params", {})

            if not task:
                return [types.TextContent(type="text", text="Error: 'task' is required.")]

            # Search for best workflow
            results = await call_flow_finder(task, top_k=3)

            if not results:
                return [types.TextContent(
                    type="text",
                    text=f"No matching automation found for: '{task}'. Try describing it differently or check if the relevant n8n workflow is indexed."
                )]

            best = results[0]
            wf_id = best["workflow_id"]
            wf_name = best["name"]
            confidence = best.get("confidence_pct", "?")

            # Execute it
            result = await execute_workflow(wf_id, task, params)

            if result.get("demo_mode"):
                return [types.TextContent(
                    type="text",
                    text=(
                        f"Found workflow: **{wf_name}** ({confidence} match)\n\n"
                        f"⚠️ Cannot execute yet — no webhook configured.\n"
                        f"To enable: add `N8N_WEBHOOK_{wf_id}=<your-webhook-url>` to your .env file.\n\n"
                        f"📖 View this workflow: {best.get('source_url', 'https://n8n.io')}\n"
                        f"📝 Description: {best.get('description', '')}"
                    )
                )]
            elif result.get("success"):
                return [types.TextContent(
                    type="text",
                    text=(
                        f"✅ Automation executed: **{wf_name}**\n"
                        f"Match confidence: {confidence}\n"
                        f"Status: HTTP {result.get('status_code', 'OK')}\n\n"
                        f"Response: {result.get('response', 'Workflow completed successfully.')}"
                    )
                )]
            else:
                return [types.TextContent(
                    type="text",
                    text=f"❌ Execution failed: {result.get('detail', result.get('error', 'Unknown error'))}"
                )]

        # ── List automations ──────────────────────────────────────────────────
        elif name == "list_automations":
            query = arguments.get("query", "")
            limit = min(int(arguments.get("limit", 5)), 10)

            results = await call_flow_finder(query, top_k=limit)

            if not results:
                return [types.TextContent(type="text", text=f"No automations found matching '{query}'.")]

            lines = [f"Found {len(results)} automation(s) for '{query}':\n"]
            for i, r in enumerate(results, 1):
                lines.append(
                    f"{i}. **{r['name']}** ({r.get('confidence_pct','?')} match)\n"
                    f"   {r.get('description','')[:120]}\n"
                    f"   Integrations: {', '.join(r.get('nodes',[])[:4]) or 'N/A'}\n"
                    f"   → {r.get('source_url','')}\n"
                )
            return [types.TextContent(type="text", text="\n".join(lines))]

        # ── Individual workflow tool ───────────────────────────────────────────
        else:
            # Find the workflow matching this tool name
            target_wf = None
            for wf in top_workflows:
                if workflow_to_tool_name(wf) == name:
                    target_wf = wf
                    break

            if not target_wf:
                return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

            wf_id   = target_wf["workflow_id"]
            task    = arguments.get("user_query", f"Execute workflow: {target_wf['name']}")
            params  = {k: v for k, v in arguments.items() if k != "user_query"}

            result = await execute_workflow(wf_id, task, params)

            if result.get("demo_mode"):
                return [types.TextContent(
                    type="text",
                    text=(
                        f"Workflow identified: **{target_wf['name']}**\n\n"
                        f"⚠️ No webhook configured. Add to .env:\n"
                        f"N8N_WEBHOOK_{wf_id}=<your-n8n-webhook-url>\n\n"
                        f"View: {target_wf.get('source_url', '')}"
                    )
                )]
            elif result.get("success"):
                return [types.TextContent(
                    type="text",
                    text=f"✅ {target_wf['name']} executed successfully.\n\n{result.get('response','Done.')}"
                )]
            else:
                return [types.TextContent(
                    type="text",
                    text=f"❌ Failed: {result.get('detail', 'Unknown error')}"
                )]

    # Run the server over stdio (required for MCP)
    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(main())


# ── Fallback HTTP mode (if MCP SDK not available) ────────────────────────────

def run_http_fallback():
    """
    Fallback: exposes tools over HTTP in MCP-compatible format.
    Use this if you can't install the MCP SDK.
    """
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI(title="n8n Workflows MCP (HTTP fallback)")
    top_workflows = load_top_workflows(TOP_TOOLS)

    @app.get("/tools")
    async def get_tools():
        """List all available workflow tools."""
        tools = []
        for wf in top_workflows:
            tools.append({
                "name": workflow_to_tool_name(wf),
                "description": wf.get("description", "")[:500],
                "nodes": wf.get("nodes", [])[:6],
                "workflow_id": wf["workflow_id"],
                "source_url": wf.get("source_url", ""),
                "schema": build_tool_schema(wf),
            })
        return {"tools": tools, "count": len(tools)}

    @app.post("/tools/run_automation")
    async def run_automation(body: dict):
        task   = body.get("task", "")
        params = body.get("params", {})
        results = await call_flow_finder(task, top_k=1)
        if not results:
            return {"success": False, "error": "No matching workflow found"}
        best   = results[0]
        result = await execute_workflow(best["workflow_id"], task, params)
        result["workflow_name"]       = best["name"]
        result["workflow_confidence"] = best.get("confidence_pct", "?")
        return result

    PORT = int(os.getenv("MCP_HTTP_PORT", 8001))
    print(f"[n8n MCP HTTP] Running on http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"

    if mode == "http":
        run_http_fallback()
    elif mode == "mcp" or MCP_AVAILABLE:
        run_mcp_server()
    else:
        print("MCP SDK not found. Starting HTTP fallback on port 8001...")
        print("Install MCP SDK with: pip install mcp")
        run_http_fallback()
