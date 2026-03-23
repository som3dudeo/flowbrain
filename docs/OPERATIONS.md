# Failure, Fallback, and Observability

## Failure modes you should expect

### No index
Symptom:
- `/status` shows `no_index`
- `/auto` says to run `flowbrain reindex`

Fix:
```bash
python -m flowbrain reindex
```

### No webhook configured
Symptom:
- `/auto` returns `decision: "needs-webhook"`
- `needs_webhook: true`

Fix:
- set `N8N_DEFAULT_WEBHOOK` or `N8N_WEBHOOK_<workflow_id>`
- verify the n8n workflow is active

### Confidence too low
Symptom:
- `/auto` returns `decision: "blocked"`
- block reason mentions confidence threshold

Fix:
- make the intent more specific
- name the target service explicitly
- provide missing params directly
- preview first

### High-risk action blocked
Symptom:
- block reason mentions safety policy or risk

Fix:
- keep it preview-only
- require a human confirmation step in your calling product
- reduce blast radius in the downstream workflow

### Webhook/runtime failure
Symptom:
- `/auto` returns `decision: "execution-failed"`
- `execution_result.error` is populated

Fix:
- inspect n8n health
- inspect FlowBrain logs
- inspect the receiving workflow and credentials

## Observability surfaces

### `/status`
Runtime state, security posture, and outcome summary.

### `/metrics`
Local counters from SQLite state:
- total runs
- preview-only runs
- execute requests
- successful executions
- blocked/failed runs
- missing-webhook blocks

### `python -m flowbrain logs`
Recent run history.

### `data/flowbrain.db`
Durable state for previews and runs.

## Why this matters

A lot of agent tooling is hard to trust because it hides the difference between:
- found a plausible thing
- previewed a thing
- actually executed a thing
- failed a thing

FlowBrain v2 makes those states more explicit.
