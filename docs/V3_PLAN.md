# FlowBrain v3 Plan

This pass is driven by external critiques that FlowBrain still needs stronger proof of usefulness, easier setup validation, and a more user-friendly first-run path.

## Main critique themes

1. **Use:** can a new user quickly understand what FlowBrain is good for?
2. **Working state:** can they prove it is actually routing, previewing, and delegating correctly?
3. **Setup:** can they verify a healthy install without guessing?
4. **User-friendliness:** are the first examples and surfaces honest, safe, and easy to try?

## v3 goals

### 1. Add explicit proof surfaces
- expose guided examples
- expose a fixed benchmark summary
- make the first-run story visible in both CLI and UI

### 2. Improve first-run UX
- steer users toward preview-first safe wins
- show examples that demonstrate the workflow/delegation boundary
- reduce the need to read docs before getting a result

### 3. Make setup validation simpler
- add one command that checks the most important product surfaces against a running server
- make benchmark and metrics reachable without custom scripting

## v3 execution plan

### Product surfaces
- `GET /examples` for guided first-run intents
- `GET /eval` for a fixed local benchmark summary
- `/status` advertises the examples and benchmark surfaces

### CLI
- `flowbrain examples`
- `flowbrain smoke`
- `flowbrain eval`

### UI
- refresh welcome state around safe first wins
- link to `/status`, `/metrics`, and `/eval`
- load examples from `/examples`

### Docs
- README: highlight `flowbrain smoke`
- QUICKSTART: point to examples, smoke, and eval
- CHANGELOG: document the v3 usability/proof pass

### Validation
- add tests for `/examples` and `/eval`
- keep the full suite green

## Success criteria

- a new user can run one command after startup and see whether the product is actually healthy
- a reviewer can inspect examples, metrics, and a benchmark without digging through code
- the product feels more honest about preview vs execute vs delegate
- FlowBrain is easier to critique harshly on setup/use/user-friendliness because the proof surfaces are explicit
