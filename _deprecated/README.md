# Deprecated Files

These files are kept for reference but are no longer part of the active FlowBrain system.

## mcp_server.py
**Deprecated in v2.1.0.** This MCP server implementation was never functional with OpenClaw,
which uses Skills (SKILL.md) as its integration mechanism — not MCP servers.

The official integration path is now:
- **OpenClaw**: SKILL.md installed at `~/.openclaw/workspace/skills/n8n-flows/`
- **HTTP API**: POST to `http://127.0.0.1:8001/auto` with `{"intent": "..."}`

See INTEGRATION.md in the project root for full details.
