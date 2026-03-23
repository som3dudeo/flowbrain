# Roadmap

## Now: FlowBrain as the honest agent-manager layer

Current strongest path:
- workflow automation is searchable, previewable, and conditionally executable
- coding, research, and OpenClaw ops return delegation plans

That is a feature, not a bug. It keeps the product honest.

## Near-term

### 1) Better first-run UX
- seeded demo intents
- one-command smoke test
- clearer setup verification in CLI and docs

### 2) Better policy controls
- per-integration allow/deny rules
- per-route approval policies
- richer risk explanations on blocked runs

### 3) Better retrieval evaluation
- fixed eval set
- top-k routing quality checks
- regression reporting in CI

### 4) Better execution feedback
- persist richer webhook outcomes
- optional links to n8n execution IDs
- operator-facing error classes and retries

## Beyond n8n

FlowBrain should become an execution decision layer, not an n8n-only wrapper.

Promising next adapters:
- webhook-native internal tools
- MCP/tool servers where execution semantics are strong
- queue/job systems for deferred or approval-gated execution
- agent runtimes for coding and research where handoff is explicit and observable

## Product boundary going forward

The important thing is not “support everything.”
The important thing is:
- know which paths are mature
- expose risk clearly
- execute only where the trust surface is real
- delegate honestly everywhere else
