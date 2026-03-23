# FlowBrain v2 Response to Feedback

This pass focuses on the highest-leverage issues from external feedback:

1. **Onboarding / first win**
   - added `docs/QUICKSTART.md`
   - README now points clearly to a safe preview-first path and observability surfaces

2. **Trust / safety surface**
   - added `docs/SECURITY.md`
   - added `docs/PRIVACY.md`
   - clarified what FlowBrain does and does not claim

3. **Failure / fallback / observability**
   - added `docs/OPERATIONS.md`
   - added `/metrics`
   - expanded `/status` with observability and outcome summaries
   - `/auto` and `/preview` now return `decision` and `next_step`

4. **Evidence / metrics**
   - added `docs/EVALUATION.md`
   - SQLite-backed local metrics summarize preview-vs-execute outcomes

5. **Roadmap beyond n8n**
   - added `docs/ROADMAP.md`

This is intentionally a practical one-pass upgrade, not a rewrite.
