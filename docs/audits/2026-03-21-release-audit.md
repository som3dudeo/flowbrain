# FlowBrain Release Audit — v2.4.0

**Date**: 2026-03-21
**Auditor**: Senior SWE release audit (automated)
**Branch**: main
**Scope**: Full repository — architecture, runtime correctness, safety, tests, deployment readiness

---

## 1. FINAL VERDICT

| Criterion | Status |
|---|---|
| **Launch-ready** | No |
| **Beta-ready** | Yes — with 3 caveats below |
| **Production-ready** | No |
| **Truly an agent manager** | Partially — 1 of 4 agent types actually executes |

FlowBrain is a solid workflow router with a well-designed safety model, wrapped in an agent-manager API surface that is 75% stub. The workflow-automation path (search → preview → gate → execute) is real and well-tested. The coding, research, and OpenClaw agent paths return a JSON plan but never execute anything.

---

## 2. WHAT IS SOLID

### Retrieval pipeline
Hybrid re-ranking (65% semantic + 35% keyword overlap), query expansion with 30+ regex patterns, service-name aliasing. The `embedding.py` fallback system handles offline/firewalled environments gracefully with deterministic hash-based embeddings that produce usable results, plus a clear upgrade path via `flowbrain reindex`.

### Safety model
Three-layer gating is correctly implemented and well-tested:

- **Risk classification**: Node-based (HIGH: Gmail, Slack, Twitter; MEDIUM: Notion, Jira; LOW: Webhook, Set)
- **Confidence threshold**: 85% minimum for auto-execution, MEDIUM risk needs 90%+
- **HIGH risk hard-block**: Always blocked regardless of confidence — no bypass path
- **Default mode**: `auto_execute=False` enforced at every layer (AutoRequest model, Config, CLI)

No path exists where a webhook fires without the caller explicitly requesting `auto_execute=True` AND passing all safety gates.

### Config system
Single-source `Config` frozen dataclass, dotenv loaded first, localhost-only bind by default, all env vars have sane defaults. Legacy `FLOW_FINDER_URL` → `FLOWBRAIN_URL` migration handled.

### State layer
SQLite-backed durable history for runs, previews, and doctor results. Proper schema with indexes. `_now()` correctly uses `datetime.now(timezone.utc)`.

### Memory management
`_conversations` is now an `OrderedDict` with LRU eviction (`MAX_SESSIONS=1000`). The previous unbounded `defaultdict` leak is fixed.

### Exception handling
Core files (`server.py`, `router.py`, `auto_executor.py`) now use `logging.getLogger(__name__)` and log exceptions with `logger.warning()` instead of bare `except Exception: pass`. State recording failures don't crash the endpoint.

### Import hygiene
All policy/state imports in `server.py` are now at module top level — no more lazy imports inside endpoint functions.

### Bootstrap
`bootstrap.sh` is idempotent, 5-step, no `kill -9`, exits nonzero on failure. `install.sh` delegates to it.

### Tests
56/56 pass in ~1s. Policy tests (confidence gating, risk classification, preview) cover the most safety-critical paths. Reranker tests (321 lines) are thorough. Agent routing tests include the empty-registry crash case.

### Error-path recovery
`router.py` handles stale ChromaDB collection handles with automatic `_reload_collection()` retry. Tested.

---

## 3. CRITICAL ISSUES

### C1. Version string mismatch
`flowbrain/__init__.py` has `__version__ = "2.3.0"` but CHANGELOG declares v2.4.0 with the agent manager upgrade. `flowbrain/cli/main.py:170` hardcodes `"FlowBrain v2.3.0"` in the start banner.

**Impact**: Users and integrations report wrong version.
**Fix**: Bump `__init__.py` to `"2.4.0"`, update CLI banner to use `__version__` dynamically.

### C2. Agent routing double-counts keywords
In `flowbrain/agents/router.py`, `_score_agent()` has three scoring layers that can all fire for the same word:

1. `agent.keywords` (+0.18 per match)
2. `_KEYWORD_BONUS[handler]` (+0.08 per match)
3. Handler-specific bonus (+0.15/+0.18)

Example: "slack" appears in `workflow-automation.keywords` AND `_KEYWORD_BONUS["workflow"]`. The intent "send slack message" scores `0.18 + 0.08 + 0.08 = 0.34` from "slack" alone across layers 1 and 2, plus another `0.08` from "send" in layer 2.

**Impact**: Scores are inflated and overlapping, making routing less discriminating. For "summarize email" (ambiguous — could be research or workflow), workflow-automation wins at 0.31 vs research-agent at 0.17, primarily because of double-counted "email" bonuses. A research agent should arguably win that.
**Fix**: Deduplicate — if a word matched in `agent.keywords`, skip it in `_KEYWORD_BONUS`.

### C3. `/manage` for non-workflow agents is a no-op
When `/manage` routes to coding, research, or OpenClaw handlers, it returns:
```json
{"delegation_ready": true, "next_step": "spawn-coding-agent-session"}
```
But nothing downstream acts on this. No ACP session spawns. No research happens. No OpenClaw tool fires. The caller gets a JSON blob that says "ready to delegate" with no way to actually delegate.

**Impact**: 3 of 4 advertised agent paths are dead ends. Any integration (OpenClaw, CLI, API caller) that routes to these agents gets a plan they can't execute.
**Fix**: Either implement actual delegation (out of scope for beta), or document these as "routing only — execution not yet available" in the API response itself (not just in docs).

---

## 4. MEDIUM ISSUES

### M1. `run.py` still exists and is semi-functional
It prints a deprecation warning but still offers `--setup`, `--serve`, `--rebuild`, `--no-browser` flags. Line 263 still references `python run.py --setup`. The canonical entry point is `python -m flowbrain`. Having both is confusing.

### M2. `AUDIT.md` describes the pre-fix state
The entire AUDIT.md documents phase-1 findings (port 8000 bugs, `auto_execute` flag ignored, confidence at 35%, etc.) that have all been fixed. It reads as if these are current problems. It should either be archived to `_deprecated/` or clearly marked as "historical — all items resolved."

### M3. `Config.flow_finder_url` is a legacy field name
The frozen dataclass still uses `flow_finder_url` as its canonical field. Comment says "legacy." Should be `flowbrain_url` for new code.

### M4. `auto_executor.py` duplicates config
It has its own `CONFIDENCE_THRESHOLD`, `FLOWBRAIN_URL`, `N8N_BASE_URL`, `OLLAMA_URL` loaded independently from env vars. These could diverge from `flowbrain.config.loader.Config` if import order differs.

### M5. No input sanitization on `intent` strings
Endpoints accept arbitrary-length intent strings with no max-length check. A 10MB intent string would be processed through regex expansion and ChromaDB query without truncation.

### M6. `router.py` CLI mode at bottom (`if __name__ == "__main__"`) duplicates search functionality
This is dead code now that `flowbrain search` exists. Minor, but adds maintenance surface.

---

## 5. MISLEADING CLAIMS OR DOC PROBLEMS

### D1. README title: "AI-Native Automation Operating System"
This overpromises. The system searches n8n workflows by natural language and optionally fires webhooks. That's a workflow router with a nice NLP layer, not an "operating system." The agent manager adds routing but not execution for 3 of 4 agent types.

**Honest title**: "AI-powered workflow search and execution for n8n" or "Agent-routed automation for n8n + OpenClaw."

### D2. README doesn't mention agents CLI commands
The CLI Commands table lists `install`, `doctor`, `start`, `status`, `search`, `preview`, `run`, `reindex`, `logs` — but omits `agents` and `route`, which are implemented and working.

### D3. ARCHITECTURE.md says "Non-workflow path: route → delegation plan for coding / research / OpenClaw ops"
Technically true but misleading — "delegation plan" implies something happens with the plan. Nothing does.

### D4. CHANGELOG v2.4.0 says "End-to-end validation now covers API routing plus workflow-manager behavior"
The test for `/manage` endpoint doesn't exist. There are tests for `/agents` (GET) and `/route` (POST), but nothing tests the actual `/manage` flow.

### D5. AUDIT.md is outdated
All 10 contradictions documented in AUDIT.md have been fixed. The document still reads as if they're current. Someone reviewing the repo would think there are active security issues (bind to 0.0.0.0, confidence at 35%, auto_execute ignored).

### D6. INTEGRATION.md architecture diagram references "GPT-5.4" for OpenClaw
This is a specific model assumption that may confuse users. The integration doesn't depend on the model.

---

## 6. SCALE / PRODUCTION RISKS

### S1. Single-process, no horizontal scaling
ChromaDB PersistentClient, in-memory OrderedDict for sessions, singleton router. Cannot run multiple instances behind a load balancer. Fine for local tool, not for multi-user SaaS.

### S2. No authentication or rate limiting
Server binds to 127.0.0.1 by default (good). But if `FLOWBRAIN_HOST=0.0.0.0`, all endpoints are open. No API keys, no rate limits. `/auto` with `auto_execute=true` can fire webhooks as fast as requests come in.

### S3. ChromaDB SQLite concurrency
Under concurrent async requests, ChromaDB's SQLite backend can throw `OperationalError`. The retry-reload in `router.py` helps but isn't a full solution.

### S4. Ollama dependency for advanced parameter extraction is optional and silent
If Ollama is unreachable, `auto_executor.py` falls back to regex extraction without telling the user. Complex parameter needs (multi-field forms, ambiguous entities) silently degrade.

### S5. No request timeout/cancellation
Long-running ChromaDB queries or n8n webhook calls hold the async worker. No middleware-level timeout.

---

## 7. TOP 10 NEXT FIXES

| # | Priority | File | Change |
|---|---|---|---|
| 1 | **Critical** | `flowbrain/__init__.py` | Bump `__version__` to `"2.4.0"` |
| 2 | **Critical** | `flowbrain/cli/main.py:170` | Replace hardcoded `"v2.3.0"` with `f"v{__version__}"` |
| 3 | **Critical** | `flowbrain/agents/router.py` | Deduplicate keyword scoring — skip `_KEYWORD_BONUS` words already matched in `agent.keywords` |
| 4 | **Critical** | `server.py` `/manage` endpoint | Add `"status": "routing_only"` and `"note": "Execution for this agent type is not yet implemented"` when `execution_mode != "workflow"` |
| 5 | **High** | `AUDIT.md` | Move to `_deprecated/AUDIT_PHASE1.md` or add "RESOLVED" header |
| 6 | **High** | `README.md` CLI table | Add `agents` and `route` commands |
| 7 | **High** | `README.md` title | Tone down from "Operating System" to something honest |
| 8 | **Medium** | `run.py` | Add full deprecation banner (like `mcp_server.py`) pointing to `python -m flowbrain` |
| 9 | **Medium** | `auto_executor.py` | Remove duplicated env var loading; import from `flowbrain.config` instead |
| 10 | **Medium** | `server.py` | Add `max_length` validation on `intent`/`message`/`query` fields (e.g., 2000 chars) |

---

## 8. TEST GAPS

### What's well-tested
- Confidence gating (6 tests covering all risk/confidence combinations)
- Risk classification (7 tests covering HIGH/MEDIUM/LOW/UNKNOWN + affected systems)
- Preview building (2 tests)
- Agent registry (1 test)
- Agent routing (4 tests including empty-registry ValueError)
- Reranker (25+ tests: tokeniser, alias expansion, keyword scoring, hybrid re-ranking, query expansion)
- Router runtime recovery (2 tests: stale collection handle)
- Parameter extraction (1 test: email vs Slack mention)
- State persistence (2 tests: runs + previews in SQLite)
- Config (4 tests: defaults, singleton, localhost bind, safety thresholds)
- Server agent endpoints (2 tests: GET /agents, POST /route)

### What's NOT tested (top 5 to add immediately)

1. **`/manage` endpoint** — The central agent-manager entrypoint has zero tests. Need: workflow delegation path, non-workflow delegation path, empty intent, error cases.

2. **`/auto` endpoint full pipeline** — No test exercises the search → extract → risk → gate → (block) path. Need: a mock router returning a high-risk workflow, verify it's blocked; a mock returning low-risk + high confidence, verify it would execute.

3. **`/preview` endpoint** — No integration test. Need: verify the response shape matches what the CLI expects, verify state is recorded in SQLite.

4. **Embedding fallback system** — `embedding.py` has zero tests. Need: verify `HashEmbeddingFunction` produces deterministic 384-dim unit vectors, verify `get_embedding_function()` returns fallback when model import fails.

5. **Agent routing edge cases** — "summarize email" routes to workflow-automation (arguably wrong). "send" alone scores 0.13. Need: tests documenting expected behavior for ambiguous intents, tests for score boundaries.

---

## 9. MERGE / LAUNCH DECISION

**Do not launch publicly as "agent manager" in this state.** Three of four agent types are routing-only with no execution path. Launching with this framing will immediately create a credibility problem — users will try to route coding or research tasks and get a JSON blob they can't use.

**Safe to merge to main as beta** with these conditions:

1. Fix version string (C1) — 2 minutes
2. Add honest status to `/manage` response for non-workflow agents (C3) — 5 minutes
3. Update README title and add agents/route to CLI table (D1, D2) — 5 minutes
4. Move AUDIT.md to `_deprecated/` (D5) — 1 minute

With those four changes, the product honestly represents what it does: a workflow automation system with agent-routing preview. The safety model is correct, the retrieval quality is good, and the workflow path is fully functional.

**To reach production-ready**, you'd need: authentication, rate limiting, actual execution for non-workflow agents, `/manage` and `/auto` endpoint tests, embedding fallback tests, request size limits, and either Redis-backed sessions or a proper session cleanup mechanism beyond the LRU.
