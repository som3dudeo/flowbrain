# FlowBrain ↔ OpenClaw Integration — Maintenance Guide

## What was broken

Six things were wrong, all silently failing:

**1. Wrong integration path.** `mcp_server.py` referenced an `mcpServers` config key that does not exist in OpenClaw. OpenClaw has no MCP server protocol — Skills (SKILL.md) are the only supported integration mechanism.

**2. Skill in wrong location.** The SKILL.md was at the bundled skills path (`/opt/homebrew/lib/node_modules/openclaw/skills/n8n-flows/`), which is the lowest-precedence location. The correct place for user-owned skills is `~/.openclaw/workspace/skills/` (highest precedence).

**3. Malformed SKILL.md frontmatter.** The `metadata` block spanned multiple lines. OpenClaw docs require metadata to be a single-line JSON object. Multi-line broke YAML parsing so the skill metadata (emoji, requires check) was silently ignored.

**4. Exec approvals blocked all shell commands.** OpenClaw exec security defaults to `deny` with `autoAllowSkills=false`. Every `curl` command the skill tried to run was silently blocked — this is why OpenClaw said it couldn't find FlowBrain.

**5. No PATH configured for exec.** OpenClaw's exec tool runs with a restricted PATH. Skill instructions now use `/usr/bin/curl` (absolute path) and the config prepends `/usr/bin` to the exec PATH.

**6. Server spammed browser tabs on restart.** The LaunchAgent started `run.py` without `--no-browser`. `run.py` sets `PORT=8000` at module level before loading `.env`, so it opened `localhost:8000` in Chrome on every restart, repeatedly.

---

## What was changed

### Files created
- `~/.openclaw/workspace/skills/n8n-flows/SKILL.md`
  Active workspace-level skill (highest precedence). Single-line frontmatter, correct metadata format, uses `/usr/bin/curl` absolute path, includes confirm-before-action rules.

### Files modified
- `~/.openclaw/exec-approvals.json`
  Added `agents.main`: `security=allowlist`, `autoAllowSkills=true`, `askFallback=allow`, with `/usr/bin/curl` in the allowlist.

- `~/.openclaw/openclaw.json`
  Added `tools.exec.pathPrepend=[/usr/bin, /usr/local/bin]`. Added `skills.load.watch=true` and `skills.entries.n8n-flows.enabled=true`.

- `~/Library/LaunchAgents/com.flowbrain.server.plist`
  Added `--no-browser` flag to prevent run.py from opening browser tabs on each start.

- `~/Documents/flowbrain/SKILL.md` (repo copy)
  Description now starts with "FlowBrain" so the AI routes to it by name. Metadata fixed to single-line JSON.

---

## Architecture (how it works now)

```
User → OpenClaw (GPT-5.4)
     → reads n8n-flows SKILL.md from ~/.openclaw/workspace/skills/
     → decides to use FlowBrain
     → exec tool runs /usr/bin/curl (approved via autoAllowSkills=true)
     → POST http://127.0.0.1:8001/manage  {"intent": "..."}
     → FlowBrain routes to the best agent
       → workflow path: search 450 indexed workflows → preview/execute via n8n
       → coding/research/OpenClaw path: return delegation plan to the caller
     → result returned to OpenClaw → shown to user
```

---

## Key paths

| Thing | Path |
|---|---|
| Workspace skill (active, highest precedence) | `~/.openclaw/workspace/skills/n8n-flows/SKILL.md` |
| Bundled skill (lower precedence, keep in sync) | `/opt/homebrew/lib/node_modules/openclaw/skills/n8n-flows/SKILL.md` |
| Repo skill (source of truth) | `~/Documents/flowbrain/SKILL.md` |
| OpenClaw config | `~/.openclaw/openclaw.json` |
| Exec approvals | `~/.openclaw/exec-approvals.json` |
| LaunchAgent (auto-start on login) | `~/Library/LaunchAgents/com.flowbrain.server.plist` |
| FlowBrain server | `http://127.0.0.1:8001` |
| n8n dispatcher webhook | `http://localhost:5678/webhook/flowbrain` |
| FlowBrain server log | `~/Documents/flowbrain/server.log` |
| FlowBrain env config | `~/Documents/flowbrain/.env` |

---

## How OpenClaw config hot-reloads

`openclaw.json` is file-watched by the gateway (hybrid mode). Changes to `tools` and `skills` take effect on the next agent turn — no restart needed. `exec-approvals.json` is read at exec time so changes are immediate. To force a full reload: `kill -HUP $(pgrep openclaw-gateway)`

---

## Verification commands

```bash
# FlowBrain server health
curl -s http://127.0.0.1:8001/status

# Search workflows
curl -s -X POST http://127.0.0.1:8001/search \
  -H "Content-Type: application/json" \
  -d '{"query": "slack message", "top_k": 3}'

# Full automation run (safe test)
curl -s -X POST http://127.0.0.1:8001/auto \
  -H "Content-Type: application/json" \
  -d '{"intent": "search for Slack notification workflows"}'

# OpenClaw gateway health
curl -s http://127.0.0.1:18789/health

# LaunchAgent status
launchctl list | grep flowbrain
```

---

## Troubleshooting

**"can't find FlowBrain" from OpenClaw**
1. Check server: `curl -s http://127.0.0.1:8001/status`
2. If down: `launchctl start com.flowbrain.server`
3. Check exec-approvals.json has `agents.main.autoAllowSkills=true`

**Skill not triggering**
1. Confirm `~/.openclaw/workspace/skills/n8n-flows/SKILL.md` exists
2. Check `skills.entries.n8n-flows.enabled=true` in `openclaw.json`
3. Try being explicit: "use FlowBrain to [task]"

**Browser tabs opening on login**
Check LaunchAgent has `--no-browser`: `grep no-browser ~/Library/LaunchAgents/com.flowbrain.server.plist`

**n8n webhook not firing (needs_webhook: true)**
1. Check n8n is running: `curl -s http://localhost:5678/healthz`
2. Check `~/Documents/flowbrain/.env` has `N8N_DEFAULT_WEBHOOK` set
3. In n8n UI: verify the ⚡ FlowBrain Dispatcher workflow is active

**Updating the skill**
Edit `~/Documents/flowbrain/SKILL.md`, then sync both copies:
```bash
cp ~/Documents/flowbrain/SKILL.md ~/.openclaw/workspace/skills/n8n-flows/SKILL.md
cp ~/Documents/flowbrain/SKILL.md /opt/homebrew/lib/node_modules/openclaw/skills/n8n-flows/SKILL.md
```
