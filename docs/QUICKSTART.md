# FlowBrain Quickstart

This is the shortest path to a real first win.

## 1) Start FlowBrain

```bash
git clone https://github.com/som3dudeo/flowbrain.git ~/Documents/flowbrain
cd ~/Documents/flowbrain
bash bootstrap.sh
source venv/bin/activate
python -m flowbrain start
```

In another terminal:

```bash
curl -s http://127.0.0.1:8001/status | jq
```

You want to see:
- `status: "ready"`
- `workflows_indexed > 0`
- `security.localhost_only: true`

## 2) Get a safe first win

Start with preview mode. Do not wire live webhooks yet.

```bash
curl -s -X POST http://127.0.0.1:8001/preview \
  -H "Content-Type: application/json" \
  -d '{"intent":"send a slack message when deploy finishes"}' | jq
```

Look for:
- `workflow_name`
- `confidence_pct`
- `risk_level`
- `decision`
- `next_step`

If the match looks wrong, tighten the intent:
- name the service explicitly (`Slack`, `Gmail`, `Notion`)
- mention the desired trigger or output
- pass explicit params when needed

## 3) Try the agent-manager path

```bash
curl -s -X POST http://127.0.0.1:8001/manage \
  -H "Content-Type: application/json" \
  -d '{"intent":"fix this repo bug and add tests"}' | jq
```

Expected behavior:
- workflow requests go to the workflow path
- coding/research/OpenClaw requests return a delegation plan instead of fake autonomy

## 4) Only then wire n8n execution

Set a dispatcher webhook in `.env`:

```bash
N8N_DEFAULT_WEBHOOK=http://localhost:5678/webhook/flowbrain
```

Now request execution explicitly:

```bash
curl -s -X POST http://127.0.0.1:8001/auto \
  -H "Content-Type: application/json" \
  -d '{"intent":"send a slack message when deploy finishes","auto_execute":true}' | jq
```

Expected behavior:
- low confidence => blocked
- high risk => blocked or preview-first
- missing webhook => `decision: "needs-webhook"`
- allowed + configured => `decision: "executed"`

## 5) Inspect what happened

```bash
curl -s http://127.0.0.1:8001/metrics | jq
python -m flowbrain status
python -m flowbrain logs
```

This gives you local evidence about:
- preview-only vs execute attempts
- successful executions
- blocked/failed runs
- missing-webhook friction

## Recommended first demo script

If you want to show FlowBrain in under 2 minutes:
1. `/status`
2. `/preview` with a Slack-style request
3. `/manage` with a coding request
4. `/metrics`

That sequence shows the product honestly:
- retrieval
- safety gating
- delegation instead of pretending
- observable outcomes
