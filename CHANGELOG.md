# Changelog

## v2.5.0 — Public Beta Polish + Hardening

### Public Release Polish
- Rewrote the README around the actual product: an agent manager for OpenClaw + n8n.
- Added MIT `LICENSE`.
- Moved release-audit material out of the repo root into `docs/audits/` and `_deprecated/`.
- Updated legacy launcher and web UI copy to match the new agent-manager positioning.

### Runtime Hardening
- Added structured logging config plus auth, rate-limit, and tracing middleware.
- Added bounded in-memory session history with LRU-style eviction.
- Replaced silent exception paths with logging in the core runtime.
- Added delegation-plan support for non-workflow agent routes.
- Added request-size validation and extra integration tests for `/manage`, `/auto`, `/preview`, middleware, and embeddings.

---

## v2.4.0 — Agent Manager Upgrade

### Agent Management
- Added `flowbrain.agents` package with a built-in agent registry and optional file-backed overrides.
- Added agent-routing engine that chooses between workflow automation, coding, research, and OpenClaw orchestration handlers.
- Added API endpoints: `/agents`, `/route`, and `/manage`.
- Added CLI commands: `flowbrain agents` and `flowbrain route`.
- `/status` now reports the number of registered agents.
- `/chat` now returns agent-route metadata alongside workflow matches.

### Validation
- Added tests for agent registry, routing decisions, and agent-manager endpoints.
- End-to-end validation now covers API routing plus workflow-manager behavior.

---

## v2.3.0 — Offline-Resilient Index + Final Consistency Pass

### Embedding System
- **Offline fallback**: New `embedding.py` factory tries real sentence-transformers model, falls back to deterministic hash-based embeddings when model download is blocked (firewalled/offline environments).
- ChromaDB-compatible interface (`embed_query`, `embed_documents`, `name()`).
- `indexer.py` and `router.py` now use shared `embedding.py` factory — no more duplicated model loading.
- Doctor reports embedding model quality (real vs fallback).

### Bootstrap
- `bootstrap.sh` rewritten: 5 steps (Python check, venv, deps, .env, `flowbrain install`), idempotent, no `kill -9`.
- `install.sh` rewritten: clone + delegate to `bootstrap.sh`, no stale `run.py --serve` or port 8000 references.
- README Quick Start shows both `git clone && bash bootstrap.sh` and `curl | bash` paths.

### Consistency
- All error messages in `server.py` now point to `flowbrain reindex` (was `python run.py --setup`).
- `Dockerfile`: includes `embedding.py`, port 8001, uses `python -m flowbrain start`.
- `docker-compose.yml`: service renamed `flowbrain`, port 8001.
- `n8n_dispatcher.json`: branding updated.
- `requirements.txt`, `SKILL.md`, `README.md`: all consistent with FlowBrain naming.
- Version bumped to v2.3.0.

---

## v2.2.0 — Retrieval Quality + One-Command Setup

### Retrieval Quality
- **Hybrid re-ranking**: New `reranker.py` combines semantic search (65%) with keyword overlap scoring (35%) to fix broad-query results.
- **Query expansion**: 30+ patterns map user terms ("email", "tweet on x", "summarize") to service names the embeddings understand.
- **Service-name aliases**: "email" expands to ["gmail", "sendgrid", ...] so keyword scoring matches across vocabulary gaps.
- **Enriched document builder**: `indexer.py` now produces richer embedding documents with node synonyms and repeated titles.
- Run `flowbrain reindex` to rebuild the index with improved document construction.

### One-Command Setup
- **`bootstrap.sh`**: True single-command setup from zero. Checks Python 3.10+, creates venv, installs all deps, runs `flowbrain install`.
- **`flowbrain install`**: Now the canonical post-clone setup command (deps + download + index + doctor).
- **`flowbrain reindex`**: New command to rebuild the search index after upgrades.
- `setup.sh` now delegates to `bootstrap.sh`.

### Consistency Fixes
- Server web UI branding: "n8n Flow Finder" → "FlowBrain" in title, header, welcome text.
- `run.py` description: "n8n Flow Finder" → "FlowBrain".
- `SKILL.md` heading: "n8n Flow Finder" → "FlowBrain", server start command updated.
- README: Added `install` and `reindex` to CLI table, documented `bootstrap.sh`, added Python 3.10+ requirement.
- `pytest>=8.0.0` added to requirements.txt so tests run from fresh setup.

### Tests
- 45 tests total (was 20): 25 new tests cover tokeniser, alias expansion, keyword scoring, hybrid re-ranking, and query expansion.

---

## v2.1.0 — The Safety & Architecture Upgrade

### Architecture
- Created `flowbrain/` Python package with proper module structure
- Added `flowbrain.config` — config loaded FIRST, before any port/URL usage
- Added `flowbrain.policies` — confidence gating, risk classification, preview mode
- Added `flowbrain.state` — SQLite-backed run history and audit trail
- Added `flowbrain.diagnostics` — comprehensive doctor health checks
- Added `flowbrain.cli` — full CLI with doctor, start, status, search, preview, run, logs

### Critical Bug Fixes
- **Fixed dotenv load order**: PORT was read at module level BEFORE `load_dotenv()` was called, causing PORT to always default to 8000 regardless of .env. Now dotenv loads first.
- **Fixed bind address**: Server now defaults to `127.0.0.1` (localhost only) instead of `0.0.0.0` (exposed to network).
- **Fixed default port**: Changed from 8000 to 8001 everywhere (avoids Docker conflicts).
- **Removed browser auto-open**: `webbrowser.open()` no longer fires on server start.
- **Fixed FLOW_FINDER_URL default**: Changed from `localhost:8000` to `127.0.0.1:8001` in auto_executor.py.

### Safety Improvements
- **Confidence threshold raised**: Auto-execution now requires 85% confidence (was 35%).
- **Risk classification**: Workflows classified as LOW/MEDIUM/HIGH based on node types.
- **HIGH risk blocking**: Email, Slack, social media workflows never auto-execute.
- **Preview mode**: New `/preview` endpoint shows what would happen without executing.
- **auto_execute honored**: The `auto_execute` flag in `/auto` is now actually respected.

### Durable State
- SQLite database at `data/flowbrain.db` stores all runs and previews.
- Runs persist across server restarts.
- Doctor results are recorded for diagnostics.

### Documentation
- Rewrote README.md with accurate workflow count (450+, not "8,000+").
- Updated .env.example with all new config variables.
- Created AUDIT.md documenting all discovered contradictions.
- Created ARCHITECTURE.md with locked design decisions.
- Fixed SKILL.md metadata format (single-line JSON for OpenClaw).

### Deprecations
- `mcp_server.py` moved to `_deprecated/` (never functional with OpenClaw).
- `OPENCLAW.md` moved to `_deprecated/` (replaced by INTEGRATION.md).

### Tests
- 20 tests covering config, policies, risk classification, state persistence.
- Benchmark fixtures for 10 common automation intents.
