# Connecting n8n Flow Finder with OpenClaw

This guide explains how to connect OpenClaw as your conversational front-end to n8n Flow Finder, creating a complete system where you speak naturally to OpenClaw and it triggers the right n8n workflow automatically.

## How the complete loop works

```
You (voice/text)
      ↓
  OpenClaw               ← understands intent, holds conversation
      ↓
  Flow Finder API        ← finds the right workflow from thousands
      ↓
  n8n Dispatcher         ← executes the workflow
      ↓
  Target n8n Workflow    ← does the actual automation
      ↓
  Result back to you     ← via OpenClaw
```

---

## Step 1 — Make sure Flow Finder is running

```bash
python run.py --serve
# Server running at http://localhost:8000
```

Or with Docker:
```bash
docker compose up -d
```

---

## Step 2 — Import and activate the dispatcher in n8n

1. Open your n8n editor at `http://localhost:5678`
2. Click **Import from File** and select `n8n_dispatcher.json`
3. Click **Activate** (toggle in top-right)
4. Click the **Receive Dispatch Request** webhook node
5. Copy the **Production URL** — it looks like:
   `http://localhost:5678/webhook/flow-finder-dispatch`
6. Add it to your `.env` file:
   ```
   N8N_DEFAULT_WEBHOOK=http://localhost:5678/webhook/flow-finder-dispatch
   ```
7. Restart Flow Finder

---

## Step 3 — Add Flow Finder as an OpenClaw skill

In your OpenClaw configuration, add a new tool/skill that calls the `/chat` endpoint:

### OpenClaw Tool Definition

```json
{
  "name": "find_and_run_workflow",
  "description": "Searches thousands of n8n automation workflows and executes the best match for the user's request. Use this whenever the user wants to automate something, trigger a workflow, or connect two services.",
  "endpoint": "http://localhost:8000/chat",
  "method": "POST",
  "headers": {
    "Content-Type": "application/json"
  },
  "body_template": {
    "message": "{{user_input}}",
    "session_id": "{{session_id}}",
    "top_k": 3
  }
}
```

### What OpenClaw should do with the response

The `/chat` endpoint returns:
```json
{
  "reply":      "I found 3 workflows matching your request...",
  "workflows":  [...],
  "session_id": "abc-123",
  "count":      3
}
```

- Show `reply` to the user as OpenClaw's response
- Optionally show the workflow cards from `workflows`
- Store `session_id` and pass it in future requests to maintain conversation context

---

## Step 4 — Test the full loop

Try saying to OpenClaw:

> "Notify my Slack channel when someone submits a Typeform"

OpenClaw calls Flow Finder → Flow Finder finds the best workflow → Returns the match → OpenClaw presents it → User confirms → Execute is called → n8n runs the workflow.

---

## API Reference

All endpoints accept and return JSON.

### `POST /chat` — Main endpoint for OpenClaw
```json
Request:
{
  "message":    "what the user said",
  "session_id": "optional — pass back to maintain context",
  "top_k":      3
}

Response:
{
  "reply":      "Human-readable response for OpenClaw to display",
  "workflows":  [{ "workflow_id", "name", "description", "nodes", "confidence", "source_url" }],
  "session_id": "use this in your next request",
  "count":      3
}
```

### `POST /execute` — Trigger a specific workflow
```json
Request:
{
  "workflow_id": "1234",
  "query":       "original user message",
  "params":      { "any": "extra params" }
}

Response:
{
  "success":     true,
  "workflow_id": "1234",
  "status_code": 200,
  "response":    "n8n response body"
}
```

### `POST /search` — Raw semantic search (no conversation context)
```json
Request:  { "query": "send slack message", "top_k": 5 }
Response: { "query": "...", "count": 5, "results": [...] }
```

### `GET /status` — Health check
```json
{
  "status":            "ready",
  "workflows_indexed":  2000,
  "n8n_connected":      true,
  "n8n_url":           "http://localhost:5678"
}
```

---

## Configuring specific workflow webhooks

For workflows you use frequently, you can set dedicated webhook URLs instead of routing through the dispatcher. This is faster and more reliable.

In your n8n workflow:
1. Add a **Webhook** node as the trigger
2. Activate the workflow
3. Copy the Production URL
4. Add to `.env`:
   ```
   N8N_WEBHOOK_1234=http://localhost:5678/webhook/your-webhook-id
   ```
   (where `1234` is the workflow ID shown in Flow Finder results)

---

## Troubleshooting

**OpenClaw gets no response from Flow Finder**
→ Check that `python run.py --serve` is running and accessible at `http://localhost:8000`

**Execute returns "demo mode"**
→ Add `N8N_DEFAULT_WEBHOOK` or `N8N_WEBHOOK_<id>` to your `.env` and restart

**n8n dispatcher fails to execute target workflow**
→ The target workflow must be active in n8n and have a compatible trigger (not just a Webhook trigger — use "Execute Workflow" trigger instead for dispatcher-called workflows)

**Low confidence matches**
→ Try more specific queries with service names. Run `python enricher.py` to improve workflow descriptions.
