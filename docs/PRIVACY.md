# Privacy Notes

FlowBrain stores operational state locally so it can be auditable.

## What is stored locally

In `data/flowbrain.db`:
- intents
- selected workflow metadata
- extracted params
- preview records
- run outcomes
- execution errors
- timing data

Potentially in logs:
- request IDs
- server/runtime warnings
- health and middleware events

## What may leave the machine

Only when you explicitly enable downstream integrations, such as:
- n8n webhooks
- external services triggered by n8n
- optional model/runtime dependencies you choose to run

## What this means in practice

If a user types sensitive content into FlowBrain, that content may be written to:
- SQLite state
- console/file logs
- downstream webhook payloads

So treat FlowBrain like an automation control plane, not a sealed vault.

## Good hygiene

- run locally when possible
- avoid real secrets in demo prompts
- protect the host machine
- enable auth before exposing it beyond localhost
- review `data/flowbrain.db` and log retention if you handle sensitive business data

## No fake privacy promises

FlowBrain is privacy-friendlier than many cloud-only tools because it runs locally.
But local does not mean zero data persistence.
