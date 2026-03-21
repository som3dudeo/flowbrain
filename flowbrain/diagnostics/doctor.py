"""
FlowBrain Doctor — comprehensive health check.

Checks: Python version, dependencies, config, ports, server, n8n,
index, storage, OpenClaw skill, log directory.
"""

import sys
import os
import shutil
import json
from pathlib import Path

from flowbrain.config import get_config


BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"


def _ok(name: str, detail: str = ""):
    print(f"  {GREEN}✓{RESET}  {name}" + (f"  {DIM}{detail}{RESET}" if detail else ""))
    return {"name": name, "status": "ok", "detail": detail}


def _warn(name: str, detail: str = ""):
    print(f"  {YELLOW}⚠{RESET}  {name}" + (f"  {DIM}{detail}{RESET}" if detail else ""))
    return {"name": name, "status": "warn", "detail": detail}


def _fail(name: str, detail: str = ""):
    print(f"  {RED}✗{RESET}  {name}" + (f"  {DIM}{detail}{RESET}" if detail else ""))
    return {"name": name, "status": "fail", "detail": detail}


def run_doctor(verbose: bool = False) -> dict:
    """Run all health checks. Returns summary dict."""
    cfg = get_config()
    checks = []
    passed = warned = failed = 0

    print(f"\n{BOLD}FlowBrain Doctor{RESET}")
    print(f"{'─' * 50}\n")

    # 1. Python version
    v = sys.version_info
    if v >= (3, 10):
        r = _ok("Python version", f"{v.major}.{v.minor}.{v.micro}")
    else:
        r = _fail("Python version", f"{v.major}.{v.minor} — need 3.10+")
    checks.append(r)

    # 2. Required packages
    required = ["chromadb", "sentence_transformers", "fastapi", "uvicorn", "httpx", "pydantic", "tqdm", "requests"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if not missing:
        r = _ok("Python packages", f"all {len(required)} installed")
    else:
        r = _fail("Python packages", f"missing: {', '.join(missing)}")
    checks.append(r)

    # 3. dotenv
    try:
        import dotenv
        r = _ok("python-dotenv", dotenv.__version__ if hasattr(dotenv, '__version__') else "installed")
    except ImportError:
        r = _warn("python-dotenv", "not installed — .env files won't load")
    checks.append(r)

    # 4. .env file
    env_path = Path(cfg.project_root) / ".env"
    if env_path.exists():
        r = _ok(".env file", str(env_path))
    else:
        r = _warn(".env file", "not found — using defaults")
    checks.append(r)

    # 5. Port config
    r = _ok("Port", f"{cfg.port}") if cfg.port > 0 else _fail("Port", "invalid")
    checks.append(r)

    # 6. Bind address
    if cfg.host in ("127.0.0.1", "localhost", "::1"):
        r = _ok("Bind address", f"{cfg.host} (localhost only)")
    else:
        r = _warn("Bind address", f"{cfg.host} — exposed to network!")
    checks.append(r)

    # 7. Server reachability
    try:
        import httpx
        resp = httpx.get(f"http://{cfg.host}:{cfg.port}/status", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            wf_count = data.get("workflows_indexed", 0)
            r = _ok("FlowBrain server", f"running — {wf_count} workflows indexed")
        else:
            r = _fail("FlowBrain server", f"HTTP {resp.status_code}")
    except Exception:
        r = _warn("FlowBrain server", "not running (start with: flowbrain start)")
    checks.append(r)

    # 8. n8n reachability
    try:
        import httpx
        resp = httpx.get(f"{cfg.n8n_base_url}/healthz", timeout=3)
        if resp.status_code == 200:
            r = _ok("n8n", f"connected at {cfg.n8n_base_url}")
        else:
            r = _warn("n8n", f"returned HTTP {resp.status_code}")
    except Exception:
        r = _warn("n8n", f"not reachable at {cfg.n8n_base_url}")
    checks.append(r)

    # 9. Webhook config
    if cfg.n8n_default_webhook:
        r = _ok("n8n webhook", cfg.n8n_default_webhook)
    else:
        r = _warn("n8n webhook", "not configured — automations won't execute")
    checks.append(r)

    # 10. ChromaDB index
    chroma_path = Path(cfg.data_dir) / "chroma_db"
    if chroma_path.exists() and any(chroma_path.iterdir()):
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(chroma_path))
            coll = client.get_collection("n8n_workflows")
            count = coll.count()
            r = _ok("Search index", f"{count} workflows in ChromaDB")
        except Exception as e:
            r = _fail("Search index", f"exists but error: {e}")
    else:
        r = _fail("Search index", "not built — run: flowbrain reindex")
    checks.append(r)

    # 11. Workflow data
    wf_dir = Path(cfg.data_dir) / "workflows"
    if wf_dir.exists():
        wf_count = len(list(wf_dir.glob("*.json")))
        r = _ok("Workflow data", f"{wf_count} JSON files in {wf_dir}")
    else:
        r = _fail("Workflow data", "no workflows downloaded")
    checks.append(r)

    # 12. SQLite state DB
    db_path = Path(cfg.db_path)
    if db_path.exists():
        size = db_path.stat().st_size
        r = _ok("State database", f"{size:,} bytes at {db_path}")
    else:
        r = _ok("State database", "will be created on first use")
    checks.append(r)

    # 13. Log directory
    log_dir = Path(cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    if os.access(str(log_dir), os.W_OK):
        r = _ok("Log directory", str(log_dir))
    else:
        r = _fail("Log directory", f"not writable: {log_dir}")
    checks.append(r)

    # 14. Safety thresholds
    if cfg.min_autoexec_confidence >= 0.70:
        r = _ok("Auto-exec threshold", f"{cfg.min_autoexec_confidence:.0%}")
    else:
        r = _warn("Auto-exec threshold", f"{cfg.min_autoexec_confidence:.0%} — dangerously low!")
    checks.append(r)

    # 15. Embedding model quality
    try:
        from embedding import get_embedding_function, is_using_fallback
        get_embedding_function()
        if is_using_fallback():
            r = _warn("Embedding model", "using offline fallback — run `flowbrain reindex` with internet to upgrade")
        else:
            r = _ok("Embedding model", f"sentence-transformers (all-MiniLM-L6-v2)")
    except Exception as e:
        r = _warn("Embedding model", f"could not check: {e}")
    checks.append(r)

    # 16. OpenClaw skill (optional)
    openclaw_skill = Path.home() / ".openclaw" / "workspace" / "skills" / "n8n-flows" / "SKILL.md"
    if openclaw_skill.exists():
        r = _ok("OpenClaw skill", str(openclaw_skill))
    else:
        # Check if OpenClaw is even installed
        openclaw_dir = Path.home() / ".openclaw"
        if openclaw_dir.exists():
            r = _warn("OpenClaw skill", "OpenClaw found but skill not installed")
        else:
            r = _ok("OpenClaw skill", "OpenClaw not installed (skipped)")
    checks.append(r)

    # Summary
    for c in checks:
        if c["status"] == "ok":
            passed += 1
        elif c["status"] == "warn":
            warned += 1
        else:
            failed += 1

    print(f"\n{'─' * 50}")
    summary_parts = [f"{GREEN}{passed} passed{RESET}"]
    if warned:
        summary_parts.append(f"{YELLOW}{warned} warnings{RESET}")
    if failed:
        summary_parts.append(f"{RED}{failed} failed{RESET}")
    print(f"  {', '.join(summary_parts)}")
    print()

    # Persist doctor result
    try:
        from flowbrain.state.db import record_doctor
        record_doctor(checks, passed, failed, warned)
    except Exception:
        pass

    return {"checks": checks, "passed": passed, "failed": failed, "warnings": warned}
