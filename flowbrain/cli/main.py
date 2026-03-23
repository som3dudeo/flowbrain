"""
FlowBrain CLI — main entry point.

Requires Python 3.10+.

Usage:
  python -m flowbrain install                Install deps + download + index
  python -m flowbrain doctor                 Check system health
  python -m flowbrain start                  Start the server
  python -m flowbrain status                 Show server status
  python -m flowbrain search "slack msg"     Search for workflows
  python -m flowbrain preview "email bob"    Preview without executing
  python -m flowbrain run "post to #general" Execute an automation
  python -m flowbrain logs                   Show recent run history
"""

import sys
import os
import argparse
import json
import time
import subprocess
import shutil
from pathlib import Path

# ── Python version gate (hard fail) ─────────────────────────────────────────
if sys.version_info < (3, 10):
    print(f"Error: FlowBrain requires Python 3.10+. You have {sys.version.split()[0]}.")
    print("Download: https://www.python.org/downloads/")
    sys.exit(1)

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
os.chdir(str(_PROJECT_ROOT))

from flowbrain import __version__
from flowbrain.agents import list_agents as list_registered_agents, route_request
from flowbrain.config import get_config

BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"


# ── install ──────────────────────────────────────────────────────────────────

def cmd_install(args):
    """One-command setup: deps → .env → download workflows → build index → doctor."""
    print(f"\n{BOLD}FlowBrain Installer{RESET}")
    print(f"{'─' * 50}\n")

    steps_total = 5
    ok_count = 0

    # Step 1: Python deps
    _step(1, steps_total, "Installing Python dependencies")
    req_file = _PROJECT_ROOT / "requirements.txt"
    if not req_file.exists():
        _fail("requirements.txt not found")
        sys.exit(1)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(req_file)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        _fail(f"pip install failed:\n{result.stderr[:500]}")
        sys.exit(1)
    _ok("All packages installed")
    ok_count += 1

    # Step 2: .env
    _step(2, steps_total, "Checking configuration")
    env_file = _PROJECT_ROOT / ".env"
    env_example = _PROJECT_ROOT / ".env.example"
    if not env_file.exists() and env_example.exists():
        shutil.copy(str(env_example), str(env_file))
        _ok("Created .env from .env.example")
        _warn("Edit .env to set N8N_DEFAULT_WEBHOOK for live execution")
    elif env_file.exists():
        _ok(".env already exists")
    else:
        _warn("No .env or .env.example found — using defaults")
    ok_count += 1

    # Step 3: Download workflows
    _step(3, steps_total, "Checking workflow library")
    wf_dir = _PROJECT_ROOT / "data" / "workflows"
    wf_count = len(list(wf_dir.glob("*.json"))) if wf_dir.exists() else 0
    if wf_count == 0:
        print(f"    Downloading workflows from n8n.io (this takes ~3 minutes)...")
        try:
            from harvester import fetch_all_workflows
            wf_count = fetch_all_workflows(max_workflows=2000)
            if wf_count > 0:
                _ok(f"Downloaded {wf_count} workflows")
            else:
                _fail("Download returned 0 workflows")
        except Exception as e:
            _fail(f"Download failed: {e}")
    else:
        _ok(f"{wf_count} workflows already downloaded")
    ok_count += 1

    # Step 4: Build index
    _step(4, steps_total, "Building search index")
    chroma_path = _PROJECT_ROOT / "data" / "chroma_db"
    needs_build = not chroma_path.exists() or not any(chroma_path.iterdir()) if chroma_path.exists() else True
    if needs_build and wf_count > 0:
        print(f"    Building vector index (first run downloads ~60 MB model)...")
        try:
            from indexer import build_index
            total = build_index(rebuild=False)
            _ok(f"Indexed {total} workflows")
        except Exception as e:
            _fail(f"Index build failed: {e}")
    elif wf_count > 0:
        try:
            from indexer import get_index_stats
            stats = get_index_stats()
            _ok(f"Index ready — {stats.get('indexed', '?')} workflows")
        except Exception:
            _ok("Index exists")
    else:
        _warn("Skipped — no workflows to index")
    ok_count += 1

    # Step 5: Doctor
    _step(5, steps_total, "Running health check")
    from flowbrain.diagnostics.doctor import run_doctor
    doc = run_doctor()
    ok_count += 1

    # Summary
    print(f"\n{'─' * 50}")
    if doc["failed"] == 0:
        print(f"{GREEN}{BOLD}  ✅ Installation complete!{RESET}\n")
    else:
        print(f"{YELLOW}{BOLD}  ⚠  Installation complete with {doc['failed']} issue(s){RESET}\n")

    print(f"  {BOLD}Next steps:{RESET}")
    print(f"    1. Start the server:  {CYAN}python -m flowbrain start{RESET}")
    print(f"    2. Check health:      {CYAN}python -m flowbrain doctor{RESET}")
    print(f"    3. Try a search:      {CYAN}python -m flowbrain search \"send slack message\"{RESET}")
    if not (env_file.exists() and "N8N_DEFAULT_WEBHOOK" in env_file.read_text()):
        print(f"\n    For live execution, edit .env and set:")
        print(f"      N8N_DEFAULT_WEBHOOK=http://localhost:5678/webhook/flowbrain")
    print()


# ── doctor ───────────────────────────────────────────────────────────────────

def cmd_doctor(args):
    """Run health checks."""
    from flowbrain.diagnostics.doctor import run_doctor
    result = run_doctor(verbose=args.verbose)
    sys.exit(1 if result["failed"] > 0 else 0)


# ── start ────────────────────────────────────────────────────────────────────

def cmd_start(args):
    """Start the FlowBrain server."""
    cfg = get_config()

    print(f"\n{BOLD}FlowBrain v{__version__}{RESET}")
    print(f"{'─' * 50}")
    print(f"  Server:   {CYAN}http://{cfg.host}:{cfg.port}{RESET}")
    print(f"  API docs: {CYAN}http://{cfg.host}:{cfg.port}/docs{RESET}")
    print(f"  Stop:     {DIM}Ctrl+C{RESET}")
    print(f"{'─' * 50}\n")

    import uvicorn
    uvicorn.run(
        "server:app",
        host=cfg.host,
        port=cfg.port,
        reload=False,
        log_level="warning",
    )


# ── status ───────────────────────────────────────────────────────────────────

def cmd_status(args):
    """Show server status."""
    cfg = get_config()
    try:
        import httpx
        resp = httpx.get(f"http://{cfg.host}:{cfg.port}/status", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            print(f"\n{BOLD}FlowBrain Status{RESET}")
            print(f"{'─' * 40}")
            print(f"  Status:     {GREEN}running{RESET}")
            print(f"  Workflows:  {data.get('workflows_indexed', 0)}")
            print(f"  n8n:        {'connected' if data.get('n8n_connected') else 'not connected'}")
            print(f"  Sessions:   {data.get('active_sessions', 0)}")
            print(f"  Agents:     {data.get('registered_agents', 0)}")
            outcomes = data.get('outcomes', {})
            if outcomes:
                print(f"  Runs:       {outcomes.get('total_runs', 0)} total | {outcomes.get('executed_successes', 0)} executed | {outcomes.get('preview_only_runs', 0)} preview-only")
                print(f"  Blocks:     {outcomes.get('blocked_or_failed_runs', 0)} blocked/failed | {outcomes.get('missing_webhook_blocks', 0)} missing webhook")
            print(f"  Endpoint:   http://{cfg.host}:{cfg.port}")
            print()
        else:
            print(f"\n  {YELLOW}Server returned HTTP {resp.status_code}{RESET}\n")
    except Exception:
        print(f"\n  {RED}FlowBrain is not running{RESET}")
        print(f"  Start with: python -m flowbrain start\n")
        sys.exit(1)


# ── agents / route ───────────────────────────────────────────────────────────

def cmd_agents(args):
    """List registered agents."""
    agents = list_registered_agents()
    print(f"\n{BOLD}Registered Agents{RESET}")
    print(f"{'─' * 70}")
    for agent in agents:
        caps = ', '.join(agent.get('capabilities', [])[:5]) or 'none'
        print(f"\n  {BOLD}{agent['name']}{RESET}  [{agent['id']}]")
        print(f"    role: {agent['role']} | handler: {agent['handler']} | safety: {agent['safety_mode']}")
        print(f"    {agent['description']}")
        print(f"    capabilities: {caps}")
    print()


def cmd_route(args):
    """Route an intent to the best agent."""
    intent = " ".join(args.intent)
    if not intent:
        print("Usage: python -m flowbrain route <intent>")
        sys.exit(1)

    plan = route_request(intent)
    print(f"\n{BOLD}Agent Route{RESET}")
    print(f"{'─' * 60}")
    print(f"  Intent:      {intent}")
    print(f"  Selected:    {plan.selected_agent['name']} ({plan.selected_agent['id']})")
    print(f"  Mode:        {plan.execution_mode}")
    print(f"  Next step:   {plan.downstream_action}")
    print(f"  Confidence:  {int(plan.score * 100)}%")
    print(f"  Approval:    {'yes' if plan.requires_human_approval else 'no'}")
    if plan.reasoning:
        print("  Why:")
        for reason in plan.reasoning[:5]:
            print(f"    - {reason}")
    print()


# ── search ───────────────────────────────────────────────────────────────────

def cmd_search(args):
    """Search for workflows."""
    cfg = get_config()
    query = " ".join(args.query)
    if not query:
        print("Usage: python -m flowbrain search <query>")
        sys.exit(1)

    try:
        import httpx
        resp = httpx.post(
            f"http://{cfg.host}:{cfg.port}/search",
            json={"query": query, "top_k": args.top_k},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])

        if not results:
            print(f"\n  No workflows found for: \"{query}\"\n")
            return

        print(f"\n{BOLD}Search Results{RESET} for \"{query}\"")
        print(f"{'─' * 60}")

        for i, r in enumerate(results, 1):
            conf = int(r["confidence"] * 100)
            color = GREEN if conf >= 65 else YELLOW if conf >= 45 else DIM
            print(f"\n  {BOLD}#{i}{RESET}  {r['name']}")
            print(f"      Confidence: {color}{conf}%{RESET}")
            nodes = r.get("nodes", [])[:5]
            if nodes:
                print(f"      Nodes: {', '.join(nodes)}")
            if r.get("description"):
                print(f"      {DIM}{r['description'][:120]}{RESET}")
            print(f"      {DIM}{r.get('source_url', '')}{RESET}")

        print(f"\n{'─' * 60}\n")

    except Exception as e:
        print(f"\n  {RED}Error: {e}{RESET}")
        print(f"  Is FlowBrain running? Start with: python -m flowbrain start\n")
        sys.exit(1)


# ── preview ──────────────────────────────────────────────────────────────────

def cmd_preview(args):
    """Preview an automation without executing."""
    cfg = get_config()
    intent = " ".join(args.intent)
    if not intent:
        print("Usage: python -m flowbrain preview <intent>")
        sys.exit(1)

    try:
        import httpx
        resp = httpx.post(
            f"http://{cfg.host}:{cfg.port}/preview",
            json={"intent": intent},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        print(f"\n{BOLD}Automation Preview{RESET}")
        print(f"{'─' * 60}")
        print(f"  Intent:      {data.get('intent', intent)}")
        print(f"  Workflow:    {BOLD}{data.get('workflow_name', 'none')}{RESET}")
        print(f"  Confidence:  {data.get('confidence_pct', '?')}")
        print(f"  Risk:        {data.get('risk_level', 'unknown')}")

        systems = data.get("systems_affected", [])
        if systems:
            print(f"  Systems:     {', '.join(systems)}")

        params = data.get("params_extracted", {})
        skip = {"user_message", "user_query"}
        useful_params = {k: v for k, v in params.items() if k not in skip and v}
        if useful_params:
            print(f"  Parameters:")
            for k, v in useful_params.items():
                print(f"    {k}: {str(v)[:80]}")

        if data.get("execution_blocked"):
            print(f"\n  {RED}Blocked: {data.get('block_reason', 'unknown')}{RESET}")
        elif data.get("would_auto_execute"):
            print(f"\n  {GREEN}Ready to execute automatically{RESET}")
        else:
            print(f"\n  {YELLOW}Manual approval required{RESET}")
            print(f"  Run with: python -m flowbrain run \"{intent}\"")

        print(f"\n{'─' * 60}\n")

    except Exception as e:
        print(f"\n  {RED}Error: {e}{RESET}")
        sys.exit(1)


# ── run ──────────────────────────────────────────────────────────────────────

def cmd_run(args):
    """Execute an automation."""
    cfg = get_config()
    intent = " ".join(args.intent)
    if not intent:
        print("Usage: python -m flowbrain run <intent>")
        sys.exit(1)

    try:
        import httpx
        resp = httpx.post(
            f"http://{cfg.host}:{cfg.port}/auto",
            json={"intent": intent, "auto_execute": True},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("auto_executed"):
            print(f"\n  {GREEN}✓{RESET}  {data.get('message', 'Done')}\n")
        elif data.get("success"):
            print(f"\n  {GREEN}✓{RESET}  {data.get('message', 'Done')}\n")
        else:
            print(f"\n  {YELLOW}⚠{RESET}  {data.get('message', 'Could not execute')}")
            if data.get("block_reason"):
                print(f"     Reason: {data['block_reason']}")
            print()

    except Exception as e:
        print(f"\n  {RED}Error: {e}{RESET}")
        sys.exit(1)


# ── logs ─────────────────────────────────────────────────────────────────────

def cmd_logs(args):
    """Show recent run history."""
    try:
        from flowbrain.state.db import get_recent_runs
        runs = get_recent_runs(limit=args.limit)

        if not runs:
            print("\n  No runs recorded yet.\n")
            return

        print(f"\n{BOLD}Recent Runs{RESET}")
        print(f"{'─' * 70}")

        for r in runs:
            status = f"{GREEN}✓{RESET}" if r.get("success") else f"{RED}✗{RESET}"
            conf = f"{int(float(r.get('confidence', 0)) * 100)}%"
            wf = (r.get("workflow_name") or "unknown")[:30]
            intent = (r.get("intent") or "")[:40]
            ts = (r.get("created_at") or "")[:19]
            print(f"  {status}  {ts}  {conf:>4}  {wf:<30}  {DIM}{intent}{RESET}")

        print(f"\n{'─' * 70}\n")

    except Exception as e:
        print(f"\n  {RED}Error: {e}{RESET}\n")


# ── reindex ──────────────────────────────────────────────────────────────

def cmd_reindex(args):
    """Rebuild the search index from scratch with enriched documents."""
    print(f"\n{BOLD}Rebuilding search index{RESET}")
    print(f"{'─' * 50}")
    print(f"  This wipes the existing index and re-embeds all workflows")
    print(f"  using enriched document construction + node synonyms.")
    print(f"  Takes ~3-5 minutes.\n")

    try:
        from indexer import build_index
        total = build_index(rebuild=True)
        if total > 0:
            print(f"\n  {GREEN}✓{RESET}  Index rebuilt with {total} workflows")
            print(f"  Restart the server to pick up the new index.\n")
        else:
            print(f"\n  {RED}✗{RESET}  Index rebuild returned 0 workflows\n")
            sys.exit(1)
    except Exception as e:
        print(f"\n  {RED}✗{RESET}  Rebuild failed: {e}\n")
        sys.exit(1)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _step(n, total, msg):
    print(f"  {CYAN}[{n}/{total}]{RESET} {BOLD}{msg}{RESET}")

def _ok(msg):
    print(f"    {GREEN}✓{RESET}  {msg}")

def _warn(msg):
    print(f"    {YELLOW}⚠{RESET}  {msg}")

def _fail(msg):
    print(f"    {RED}✗{RESET}  {msg}")


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="flowbrain",
        description="FlowBrain — agent manager for OpenClaw and n8n (requires Python 3.10+)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""{DIM}Examples:
  flowbrain install                           One-command setup
  flowbrain doctor                            Check system health
  flowbrain start                             Start the server
  flowbrain agents                            List registered agents
  flowbrain route "fix repo bug"             Show which agent would handle it
  flowbrain search "slack notification"       Find workflows
  flowbrain preview "email alice@co.com"      Preview without executing
  flowbrain run "post to #general done"       Execute an automation
  flowbrain reindex                            Rebuild search index (improves quality)
  flowbrain logs                              Show recent history{RESET}"""
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # install
    p = sub.add_parser("install", help="One-command setup (deps + download + index)")
    p.set_defaults(func=cmd_install)

    # doctor
    p = sub.add_parser("doctor", help="Run health checks")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_doctor)

    # start
    p = sub.add_parser("start", help="Start the FlowBrain server")
    p.set_defaults(func=cmd_start)

    # status
    p = sub.add_parser("status", help="Show server status")
    p.set_defaults(func=cmd_status)

    # agents
    p = sub.add_parser("agents", help="List registered agents")
    p.set_defaults(func=cmd_agents)

    # route
    p = sub.add_parser("route", help="Route an intent to the best agent")
    p.add_argument("intent", nargs="+", help="What you want handled")
    p.set_defaults(func=cmd_route)

    # search
    p = sub.add_parser("search", help="Search for workflows")
    p.add_argument("query", nargs="+", help="What to search for")
    p.add_argument("-n", "--top-k", type=int, default=5, help="Number of results")
    p.set_defaults(func=cmd_search)

    # preview
    p = sub.add_parser("preview", help="Preview an automation (no execution)")
    p.add_argument("intent", nargs="+", help="What you want to automate")
    p.set_defaults(func=cmd_preview)

    # run
    p = sub.add_parser("run", help="Execute an automation")
    p.add_argument("intent", nargs="+", help="What you want to automate")
    p.set_defaults(func=cmd_run)

    # reindex
    p = sub.add_parser("reindex", help="Rebuild search index from scratch")
    p.set_defaults(func=cmd_reindex)

    # logs
    p = sub.add_parser("logs", help="Show recent run history")
    p.add_argument("-n", "--limit", type=int, default=20, help="Number of entries")
    p.set_defaults(func=cmd_logs)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
