# FlowBrain Architecture — Decisions Locked

## Canonical Names
- **Product name**: FlowBrain
- **Package name**: `flowbrain`
- **Repo directory**: `~/Documents/flowbrain` (canonical for new installs; legacy `~/Documents/n8n-flow-finder` still works for existing setups)
- **Skill name**: `n8n-flows` (OpenClaw convention)
- **CLI command**: `python -m flowbrain` (or `flowbrain` via pip install)

## Canonical Paths
- **Config**: `.env` in project root (loaded FIRST, before any port/URL usage)
- **Data**: `./data/` (workflows, chroma_db, flowbrain.db)
- **Logs**: `./data/logs/`
- **State DB**: `./data/flowbrain.db` (SQLite)

## Canonical Ports
- **Default**: `8001` (hardcoded default, not 8000)
- **Bind**: `127.0.0.1` (localhost only by default)
- **Override**: `FLOWBRAIN_HOST` and `FLOWBRAIN_PORT` env vars (preferred over HOST/PORT)

## CLI Surface
```
flowbrain doctor     — Check health of all components
flowbrain start      — Start the server (foreground)
flowbrain status     — Show server status
flowbrain search     — Semantic search for workflows
flowbrain preview    — Preview an automation (no side effects)
flowbrain run        — Execute an automation
flowbrain logs       — Show recent logs
```

## Safety Model
- **Auto-execute threshold**: 0.85 (env: `FLOWBRAIN_MIN_AUTOEXEC_CONFIDENCE`)
- **Preview threshold**: 0.40 (below this, results shown but no preview offered)
- **Default mode**: Preview (auto_execute=False unless explicitly set)
- **Risk classification**: LOW (read-only), MEDIUM (creates/updates), HIGH (deletes, sends external messages)
- **HIGH risk actions**: Always require explicit approval regardless of confidence

## State Model
- SQLite database at `./data/flowbrain.db`
- Tables: `runs`, `previews`, `doctor_results`
- Structured JSON logs at `./data/logs/flowbrain.log`

## Integration Model
- **n8n**: HTTP webhook dispatch via `N8N_DEFAULT_WEBHOOK`
- **OpenClaw**: SKILL.md at `~/.openclaw/workspace/skills/n8n-flows/` (user-owned, highest precedence)
- **mcp_server.py**: DEPRECATED — moved to `_deprecated/` with README notice

## Deprecations
- `mcp_server.py` → `_deprecated/mcp_server.py`
- `OPENCLAW.md` → Replaced by `INTEGRATION.md`
- `setup.sh` → Replaced by `flowbrain install` (Phase 3+)
