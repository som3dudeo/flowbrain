# Security Model

FlowBrain is designed to be conservative by default.

## Default stance

- Binds to `127.0.0.1` by default
- `auto_execute=false` by default
- High-risk actions are not blindly executed
- Low-confidence matches do not auto-run
- Requests, previews, and runs are recorded in SQLite

## Built-in controls

### 1) Localhost-first exposure
Default host is localhost. That keeps the service private on a single machine unless you opt into wider exposure.

### 2) Confidence gating
Execution requires a strong match. Preview requires less confidence than execution.

### 3) Risk gating
FlowBrain classifies workflows roughly as:
- `low`: mostly internal/read-only workflow logic
- `medium`: create/update behavior
- `high`: destructive or external messaging behavior

High-risk actions require explicit human intent and may still be blocked.

### 4) Auth + rate limiting
Set `FLOWBRAIN_API_KEY` to protect POST endpoints. Rate limiting can be enabled automatically with auth or explicitly via env vars.

### 5) Traceability
Use:
- `/status`
- `/metrics`
- `python -m flowbrain logs`
- SQLite state at `data/flowbrain.db`

## What FlowBrain does not claim

- It does not guarantee a workflow is semantically correct just because retrieval looks plausible.
- It does not provide sandboxed execution of arbitrary third-party workflows.
- It is not a substitute for app-level permissions in n8n, Slack, Gmail, Notion, etc.

## Deployment advice

For local/personal use:
- keep localhost binding
- keep preview-first behavior
- enable auth if multiple local clients may call it

For team/shared use:
- set `FLOWBRAIN_API_KEY`
- enable rate limiting
- write logs to `data/logs/flowbrain.log`
- put it behind a trusted reverse proxy only if you understand the exposure tradeoffs

## Hard truth

FlowBrain reduces risk by being explicit about uncertainty.
It does not eliminate risk.
