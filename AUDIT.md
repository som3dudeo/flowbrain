# FlowBrain Phase 1 — Audit Report

## 1. Confirmed Contradictions

### 1.1 Workflow Count Claims
- **README.md**: Claims "8,000+ n8n community workflows" (line 3)
- **SKILL.md**: Claims "8,000+ n8n automation workflows" (line 17)
- **run.py**: Downloads max 2,000 (`max_workflows=2000`, line 153)
- **Runtime**: 450 workflows actually indexed (confirmed via `/status`)
- **Verdict**: FALSE ADVERTISING. Must unify to actual count.

### 1.2 Path Naming Inconsistency
- Repo directory: `~/Documents/flowbrain/` (legacy `~/Documents/n8n-flow-finder/` for existing setups)
- Git remote: `github.com/som3dudeo/flowbrain`
- install.sh INSTALL_DIR: `$HOME/Documents/flowbrain` (line 8)
- mcp_server.py docstring: `~/Documents/flowbrain/mcp_server.py` (line 25)
- LaunchAgent WorkingDirectory: `~/Documents/n8n-flow-finder`
- OpenClaw skill: references FlowBrain by name but lives at `n8n-flows`
- **Verdict**: Mixed `flowbrain` vs `n8n-flow-finder`. Pick one canonical name.

### 1.3 Port Handling
- **run.py line 31**: `PORT = int(os.getenv("PORT", 8000))` — set BEFORE `load_dotenv()` at line 213
- **server.py line 35**: `PORT = int(os.getenv("PORT", 8000))` — module-level, before any dotenv
- **auto_executor.py line 31**: `FLOW_FINDER_URL = os.getenv("FLOW_FINDER_URL", "http://localhost:8000")` — wrong default port
- **mcp_server.py line 57**: `FLOW_FINDER_URL = os.getenv("FLOW_FINDER_URL", "http://localhost:8000")` — wrong default
- **.env**: `PORT=8001` (correct)
- **.env.example**: `PORT=8001` (correct)
- **Verdict**: Dotenv load order bug means PORT defaults to 8000 everywhere except when .env is manually sourced first. The LaunchAgent uses `--serve` which calls `start_server()` which calls `load_dotenv()` but PORT is already set at module level.

### 1.4 Bind Address
- **server.py line 229 (via run.py)**: `host="0.0.0.0"` — exposes to network
- **server.py line 909 (standalone)**: `host="0.0.0.0"` — same
- **Contract requirement**: Default to `127.0.0.1` (localhost only)
- **Verdict**: SECURITY ISSUE. Must default to localhost binding.

### 1.5 auto_execute Flag
- **AutoRequest model** (server.py line 97): `auto_execute: bool = True`
- **auto endpoint** (server.py line 237-304): Never reads `req.auto_execute` — field is ignored
- **auto_executor.py**: No concept of auto_execute flag
- **Verdict**: DEAD CODE. Flag exists in API model but is never honored.

### 1.6 Confidence Threshold
- **auto_executor.py line 36**: `CONFIDENCE_THRESHOLD = 0.35` (35%)
- **router.py line 21**: `MIN_CONFIDENCE = 0.30` (30%)
- **Contract requirement**: 0.85 (85%) for auto-execution
- **Verdict**: DANGEROUSLY LOW. A 35% match can trigger real webhooks.

### 1.7 mcp_server.py Status
- References `mcpServers` config key that doesn't exist in OpenClaw
- Points to wrong path (`~/Documents/flowbrain/mcp_server.py`)
- Uses wrong default port (8000)
- HTTP fallback mode conflicts with main server (both try port 8001)
- OpenClaw uses Skills (SKILL.md), NOT MCP servers
- **Verdict**: DEAD END. Must be deprecated/archived with clear notice.

### 1.8 Silent Failures
- `enricher.py`: `except Exception: continue` (lines 193, 309)
- `auto_executor.py`: `except Exception: pass` (line 171-172) in LLM extraction
- `mcp_server.py`: `except Exception: return []` (line 161) — search failures silently return empty
- `router.py`: `except Exception as e: print(...)` (line 70) — prints but continues with broken state
- **Verdict**: Multiple silent failure points hide root causes.

### 1.9 In-Memory State
- `server.py line 40`: `_conversations: dict[str, list[dict]] = defaultdict(list)` — lost on restart
- No run history persistence
- No execution receipts
- No audit trail
- **Verdict**: All state lost on every server restart.

### 1.10 OPENCLAW.md is Stale
- References port 8000
- References `/chat` endpoint instead of `/auto`
- References old n8n_dispatcher.json import flow
- **Verdict**: Misleading documentation.

## 2. Environment Variable Loading Order

| File | When dotenv loads | Affected vars |
|---|---|---|
| run.py | Line 213 (inside `start_server()`) | PORT already set at line 31 |
| server.py | Line 905 (inside `__main__`) | PORT already set at line 35 |
| auto_executor.py | Lines 26-29 (top of file) | Correct — loads early |
| mcp_server.py | Lines 51-53 (top of file) | Correct — loads early |
| enricher.py | Never | Uses os.getenv with hardcoded defaults |
| router.py | Never | No env vars used |
| indexer.py | Never | No env vars used |
| harvester.py | Never | No env vars used |

**Critical bug**: `run.py` and `server.py` both read PORT at module level before dotenv is loaded, so .env PORT=8001 is ignored and falls back to 8000.

## 3. Current Execution Flow

```
User intent → POST /auto
  → server.py: auto() handler
    → auto_executor.py: AutoExecutor.run()
      → Step 1: POST /search to self (FLOW_FINDER_URL) — circular HTTP call
      → Step 2: Extract params (regex or Ollama LLM)
      → Step 3: POST to N8N_DEFAULT_WEBHOOK with params
    → Return AutoResult as JSON
```

**Problem with self-referencing**: auto_executor.py calls back to its own server via HTTP (`FLOW_FINDER_URL/search`). If the URL is wrong (port 8000 due to dotenv bug), it fails silently.

## 4. Risky Execution Paths

1. **Any intent at 35%+ confidence triggers real webhooks** — no preview, no confirmation
2. **No rate limiting** on /auto endpoint
3. **No input validation** beyond empty string check
4. **No output sanitization** — raw webhook responses returned to user
5. **webbrowser.open()** in run.py opens tabs in all contexts including LaunchAgent

## 5. Proposed Target Architecture

```
flowbrain/                    # Python package
  __init__.py
  __main__.py                 # CLI entry: python -m flowbrain
  cli/
    __init__.py
    main.py                   # Click/argparse CLI
    commands/                 # doctor, status, search, preview, run, etc.
  api/
    server.py                 # FastAPI app (localhost-bound)
    models.py                 # Pydantic models
  retrieval/
    router.py                 # Semantic search
    reranker.py               # Cross-encoder reranking (Phase 7)
    bm25.py                   # Lexical search (Phase 7)
  execution/
    executor.py               # AutoExecutor (safe, gated)
    extractor.py              # Parameter extraction
    dispatcher.py             # Webhook dispatch
  policies/
    confidence.py             # Confidence gating
    risk.py                   # Risk classification
    preview.py                # Preview mode
  state/
    db.py                     # SQLite run history
    logging.py                # Structured logging
  diagnostics/
    doctor.py                 # Health checks
  config/
    loader.py                 # Config + dotenv (loaded FIRST)
    defaults.py               # Default values
  integrations/
    openclaw.py               # SKILL.md management
    n8n.py                    # n8n connection
  data/                       # Runtime data (gitignored)
    workflows/
    chroma_db/
    flowbrain.db
    logs/
tests/
  test_config.py
  test_search.py
  test_preview.py
  test_executor.py
  benchmarks/
    fixtures.json
    run_benchmarks.py
```

## 6. Migration Strategy

1. **Phase 2**: Create `flowbrain/` package inside existing repo. Keep old files as compatibility shims temporarily.
2. **Phase 3**: New CLI wraps old functionality. `flowbrain doctor` validates everything.
3. **Phase 4**: Fix critical bugs (dotenv, port, bind) in existing files first, then migrate to package.
4. **Phases 5-6**: New features built directly in package structure.
5. **Phase 7**: Hybrid retrieval added to package.
6. **Phase 8**: Old top-level scripts either removed or turned into thin wrappers.

## Audit Complete

All contradictions documented. No major path/port/install inconsistency remains undiscovered. The current app's startup, indexing, search, extraction, and execution flows are understood.
