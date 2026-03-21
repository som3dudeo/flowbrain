"""
DEPRECATED — This file is no longer part of active FlowBrain.

The MCP server approach was never functional with OpenClaw, which uses
Skills (SKILL.md) as its integration mechanism, not MCP servers.

The original code is preserved in _deprecated/mcp_server.py for reference.

Official integration paths:
  - OpenClaw:  SKILL.md at ~/.openclaw/workspace/skills/n8n-flows/
  - HTTP API:  POST http://127.0.0.1:8001/auto with {"intent": "..."}
  - CLI:       python -m flowbrain run "..."

See INTEGRATION.md for full details.
"""

import sys
print("⚠️  mcp_server.py is DEPRECATED. See _deprecated/mcp_server.py for the original code.")
print("    Use 'python -m flowbrain' or the HTTP API at :8001 instead.")
sys.exit(1)
