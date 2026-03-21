# FlowBrain — AI-Native Automation Operating System

Turn natural language into real automations. FlowBrain finds the right n8n workflow, extracts parameters, previews the action safely, and executes it — all from a single command.

## Quick Start

Requires **Python 3.10+** and **git**.

```bash
# One command — from zero to ready:
git clone https://github.com/som3dudeo/flowbrain.git ~/Documents/flowbrain
cd ~/Documents/flowbrain && bash bootstrap.sh
```

Or use the remote installer (clones for you):

```bash
curl -fsSL https://raw.githubusercontent.com/som3dudeo/flowbrain/main/install.sh | bash
```

`bootstrap.sh` checks Python, creates a venv, installs all dependencies, downloads workflows, builds the search index, and runs a health check. When it finishes:

```bash
source venv/bin/activate
python -m flowbrain start
```

If you already have a venv and dependencies installed, you can skip the bootstrap and run `python -m flowbrain install` directly.

## CLI Commands

All commands are run via `python -m flowbrain <command>`.

```
flowbrain install    One-command setup (deps + download + index + doctor)
flowbrain doctor     Check system health (config, ports, n8n, index)
flowbrain start      Start the FlowBrain server on http://127.0.0.1:8001
flowbrain status     Show server status and workflow count
flowbrain search     Search for matching workflows
flowbrain preview    Preview an automation without executing
flowbrain run        Execute an automation (with safety gating)
flowbrain reindex    Rebuild search index (improves quality after upgrades)
flowbrain logs       Show recent run history
```

## How It Works

```
You → FlowBrain CLI/API
  → Query Expansion (service-name synonyms)
  → Semantic Search (ChromaDB + sentence-transformers)
  → Hybrid Re-ranking (0.65× semantic + 0.35× keyword overlap)
  → Parameter Extraction → Risk Assessment
  → Preview/Execute → n8n Webhook → Done
```

1. **Hybrid retrieval** combines embedding search with keyword scoring for better broad-query results
2. **Query expansion** maps vague terms like "email" to specific services like "Gmail"
3. **Parameter extraction** pulls emails, channels, dates from your intent
4. **Risk classification** categorizes the action (LOW/MEDIUM/HIGH) using real node metadata
5. **Confidence gating** prevents low-confidence actions from executing
6. **Preview mode** shows exactly what will happen before it does
7. **Webhook dispatch** fires the matched n8n workflow

## Safety Model

FlowBrain defaults to **safe behavior**:

- Server binds to `127.0.0.1` (localhost only) by default
- Auto-execution requires **85%+ confidence** (configurable)
- **HIGH risk** actions (email, Slack, social media) never auto-execute
- **Preview mode** is the default — you see what would happen first
- All runs are recorded in SQLite for auditability

## Connecting n8n

FlowBrain needs n8n to actually execute automations.

1. Start n8n (e.g., `docker compose up -d` or your existing instance)
2. Create a workflow with a **Webhook** node at path `flowbrain` (POST, "When Last Node Finishes")
3. Activate the workflow
4. Set in your `.env`:
   ```
   N8N_BASE_URL=http://localhost:5678
   N8N_DEFAULT_WEBHOOK=http://localhost:5678/webhook/flowbrain
   ```
5. Restart FlowBrain and run `python -m flowbrain doctor` to verify

## Configuration

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Key settings:

| Variable | Default | Description |
|---|---|---|
| `FLOWBRAIN_HOST` | `127.0.0.1` | Server bind address |
| `FLOWBRAIN_PORT` | `8001` | Server port |
| `N8N_DEFAULT_WEBHOOK` | (none) | n8n webhook URL |
| `FLOWBRAIN_MIN_AUTOEXEC_CONFIDENCE` | `0.85` | Min confidence for auto-execution |

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/status` | GET | Server health, workflow count, and agent count |
| `/agents` | GET | Registered agents and capabilities |
| `/route` | POST | Route a request to the best agent |
| `/manage` | POST | Manager decision + execution/delegation plan |
| `/search` | POST | Semantic search (returns workflow matches) |
| `/preview` | POST | Preview an automation (no side effects) |
| `/auto` | POST | Find + optionally execute a workflow |
| `/docs` | GET | Interactive API documentation |

## OpenClaw Integration

If you use OpenClaw, FlowBrain integrates as an `n8n-flows` skill. See [INTEGRATION.md](INTEGRATION.md) for setup details.

## Architecture

```
flowbrain/              Python package
  config/               Config loader (dotenv, defaults)
  cli/                  CLI (install, doctor, search, preview, run, reindex, logs)
  policies/             Safety (confidence gating, risk classification, preview)
  state/                SQLite run history and audit trail
  diagnostics/          Doctor health checks (15 checks)
server.py               FastAPI HTTP API + web UI
router.py               Semantic search engine (ChromaDB + hybrid re-ranking)
reranker.py             Keyword overlap scoring + hybrid merger
embedding.py            Embedding function factory (real model + offline fallback)
auto_executor.py        Autonomous find + extract + execute pipeline
harvester.py            Downloads workflow templates from n8n.io
indexer.py              Builds the vector search index (enriched documents)
enricher.py             Auto-generates workflow descriptions
bootstrap.sh            Single-command setup from zero
```

## License

MIT
