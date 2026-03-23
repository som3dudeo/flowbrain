# Local Evaluation Notes

This repo now exposes a small, honest evidence layer via `/metrics`.

## What it measures

From local SQLite state:
- preview-only requests
- auto-execute requests
- successful executions
- blocked/failed runs
- missing-webhook blocks
- preview block rate
- risk-level distribution

## What it does *not* measure

- semantic correctness across a benchmark set
- business success of downstream workflows
- precision/recall across all intents
- end-user satisfaction

## How to use it well

Use `/metrics` before and after product changes to answer practical questions like:
- Are users mostly previewing or actually executing?
- Are we blocked more by safety policy or by missing configuration?
- Are high-risk flows dominating usage?
- Did onboarding improvements reduce `needs-webhook` friction?

## Suggested next evaluation pass

Build a small fixed intent set with labels for:
- correct route
- acceptable top-1 workflow
- preview-vs-execute decision
- final outcome after execution

That would produce a stronger product benchmark. `/metrics` is the lightweight operational layer, not the final eval story.
