# ⚡ n8n Flow Finder — OpenClaw Automation Skill

Turn your OpenClaw AI agent into an automation powerhouse. This skill gives OpenClaw access to **8,000+ n8n community workflows** — send emails, post Slack messages, create Notion pages, trigger CI/CD, run AI pipelines, and more — all via natural language.

> **"Send the deploy notification to #engineering on Slack"**
> OpenClaw finds the right workflow, extracts the parameters, fires the webhook. Done.

---

## How It Works

```
You → OpenClaw → n8n Flow Finder (semantic search) → n8n workflow → Result
```

1. **Semantic router** — ChromaDB + sentence-transformers finds the best workflow match from 8,000+ templates
2. **Auto parameter extraction** — regex + optional Ollama LLM pulls emails, channels, dates, content from plain English
3. **Webhook execution** — fires your connected n8n workflows automatically
4. **OpenClaw skill** — the `n8n-flows` skill teaches OpenClaw when and how to use everything

---

## One-Line Install

```bash
curl -fsSL https://raw.githubusercontent.com/abdullahalbukhari/n8n-flow-finder/main/install.sh | bash
```

This will:
- Clone the repo to `~/Documents/n8n-flow-finder`
- Create a Python virtual environment and install all dependencies
- Download and index 450+ workflow templates (runs in background)
- Install the `n8n-flows` skill into your OpenClaw installation
- Start the Flow Finder server on port 8000

**Requirements:** Python 3.10+, OpenClaw, pip

---

## Manual Setup

```bash
git clone https://github.com/abdullahalbukhari/n8n-flow-finder.git ~/Documents/n8n-flow-finder
cd ~/Documents/n8n-flow-finder
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 run.py          # downloads workflows, indexes, starts server
```

---

## Connecting n8n Workflows

The skill finds and matches workflows automatically. To actually **execute** them, you need n8n running with webhook URLs:

1. Install n8n: `npm install -g n8n` or use [n8n.io](https://n8n.io)
2. Import `n8n_dispatcher.json` into your n8n instance
3. Activate the dispatcher workflow and copy its webhook URL
4. Add to `~/Documents/n8n-flow-finder/.env`:
   ```
   N8N_DEFAULT_WEBHOOK=https://your-n8n.com/webhook/dispatcher
   ```

Without n8n connected, the skill still finds the right workflow and tells you exactly which one to set up.

---

## What You Can Automate

| Category | Services |
|---|---|
| **Email** | Gmail, Outlook, SMTP |
| **Messaging** | Slack, Discord, Telegram, WhatsApp, SMS |
| **Productivity** | Notion, Airtable, Google Sheets, Jira, Linear, Trello |
| **Social** | Twitter/X, LinkedIn, Instagram, WordPress |
| **Files** | Google Drive, Dropbox, S3, PDF, CSV |
| **Dev** | GitHub, GitLab, CI/CD, webhooks, databases |
| **AI** | GPT-4 summaries, image gen, classification, OCR |
| **Monitoring** | RSS alerts, uptime checks, price tracking |

---

## Architecture

```
n8n-flow-finder/
├── run.py              # Single entrypoint — setup + serve
├── harvester.py        # Downloads 8,000+ workflows from n8n.io + GitHub
├── indexer.py          # ChromaDB vector index with sentence-transformers
├── enricher.py         # Auto-generates descriptions (Ollama / rule-based)
├── router.py           # Semantic search — finds best workflow match
├── auto_executor.py    # Full pipeline: search → extract params → execute
├── server.py           # FastAPI HTTP server (port 8000)
├── mcp_server.py       # MCP server — exposes top 50 workflows as tools
├── SKILL.md            # OpenClaw skill definition (auto-installed)
├── n8n_dispatcher.json # Importable n8n workflow for execution routing
├── docker-compose.yml  # n8n + flow-finder + ollama stack
└── requirements.txt
```

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/auto` | POST | **Main endpoint** — find + execute any workflow |
| `/search` | POST | Semantic search without executing |
| `/status` | GET | Server health + workflow count |
| `/chat` | POST | Conversational interface |

### `/auto` Example

```bash
curl -X POST http://localhost:8000/auto \
  -H "Content-Type: application/json" \
  -d '{"intent": "Send email to alice@company.com saying the report is ready"}'
```

```json
{
  "success": true,
  "workflow_name": "Send Gmail email",
  "confidence": 0.89,
  "message": "✅ Found the right automation...",
  "needs_webhook": false
}
```

---

## Docker

```bash
docker compose up -d                    # n8n + flow-finder
docker compose --profile ollama up -d  # + local LLM for smarter parameter extraction
```

---

## License

MIT — build freely, automate everything.
