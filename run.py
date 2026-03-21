"""
run.py — The single command to rule them all.

This is the ONE script you need. It guides you through the full setup
and starts the server automatically.

Usage:
  python run.py              → Full guided setup + start server
  python run.py --serve      → Skip setup, just start the server
  python run.py --setup      → Run setup only, don't start server
  python run.py --rebuild    → Rebuild index from scratch, then serve
"""

import sys
import os
import time
import argparse
import subprocess
from pathlib import Path

# ── Load dotenv FIRST — before any os.getenv calls ───────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Console colors ────────────────────────────────────────────────────────────
BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# Now safe to read PORT — dotenv already loaded
PORT = int(os.getenv("FLOWBRAIN_PORT", os.getenv("PORT", 8001)))
HOST = os.getenv("FLOWBRAIN_HOST", os.getenv("HOST", "127.0.0.1"))

def banner():
    print(f"""
{BOLD}╔══════════════════════════════════════════════════════╗
║  ⚡  FlowBrain                                        ║
║     Describe what you want → find the right workflow ║
╚══════════════════════════════════════════════════════╝{RESET}
""")

def step(n: int, total: int, msg: str):
    print(f"\n{CYAN}[{n}/{total}]{RESET} {BOLD}{msg}{RESET}")

def ok(msg: str):
    print(f"  {GREEN}✓{RESET}  {msg}")

def warn(msg: str):
    print(f"  {YELLOW}⚠{RESET}  {msg}")

def info(msg: str):
    print(f"  {DIM}→{RESET}  {msg}")

def error(msg: str):
    print(f"  {RED}✗{RESET}  {msg}")


# ── Checks ────────────────────────────────────────────────────────────────────

def check_python():
    if sys.version_info < (3, 10):
        error(f"Python 3.10+ required. You have {sys.version.split()[0]}")
        info("Download: https://www.python.org/downloads/")
        sys.exit(1)
    ok(f"Python {sys.version.split()[0]}")


def check_packages() -> bool:
    """Check if all required packages are installed."""
    required = ["chromadb", "sentence_transformers", "fastapi", "uvicorn", "httpx", "tqdm", "requests"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        warn(f"Missing packages: {', '.join(missing)}")
        return False
    ok("All packages installed")
    return True


def install_packages():
    print(f"\n  Installing packages from requirements.txt...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        error("Package installation failed. Try manually: pip install -r requirements.txt")
        print(result.stderr)
        sys.exit(1)
    ok("Packages installed successfully")


def count_workflows() -> int:
    """Return number of workflow JSON files downloaded."""
    workflows_dir = Path("./data/workflows")
    if not workflows_dir.exists():
        return 0
    return len(list(workflows_dir.glob("*.json")))


def index_is_built() -> bool:
    """Check if the ChromaDB index exists and has data."""
    chroma_path = Path("./data/chroma_db")
    return chroma_path.exists() and any(chroma_path.iterdir())


def check_env():
    """Create .env from example if missing."""
    if not Path(".env").exists():
        if Path(".env.example").exists():
            import shutil
            shutil.copy(".env.example", ".env")
            ok("Created .env from template")
            warn("Edit .env to add your n8n webhook URLs when ready")
        else:
            warn(".env file missing (optional for demo mode)")
    else:
        ok(".env file found")


# ── Setup pipeline ────────────────────────────────────────────────────────────

def run_setup(rebuild: bool = False) -> bool:
    """
    Run the full setup pipeline:
    1. Check packages
    2. Download workflows (if needed)
    3. Enrich descriptions (if needed)
    4. Build index (if needed)
    """
    TOTAL = 4
    all_ok = True

    step(1, TOTAL, "Checking Python packages")
    if not check_packages():
        print()
        install_packages()

    check_env()

    step(2, TOTAL, "Workflow library")
    wf_count = count_workflows()

    if wf_count == 0:
        print(f"\n  {YELLOW}No workflows downloaded yet.{RESET}")
        print(f"  Downloading 2,000 workflows from n8n.io...")
        print(f"  {DIM}(This runs once and takes ~5 minutes){RESET}\n")

        from harvester import fetch_all_workflows
        wf_count = fetch_all_workflows(max_workflows=2000)

        if wf_count == 0:
            error("Failed to download workflows. Check your internet connection.")
            all_ok = False
        else:
            ok(f"Downloaded {wf_count} workflows")
    else:
        ok(f"{wf_count} workflows already downloaded")
        info("Run `python harvester.py` to download more")

    step(3, TOTAL, "Enriching workflow descriptions")
    if wf_count > 0:
        try:
            from enricher import enrich_all
            enriched = enrich_all(method="auto", force=False)
            if enriched > 0:
                ok(f"Enriched {enriched} workflow descriptions")
            else:
                ok("All descriptions already enriched")
        except Exception as e:
            warn(f"Enrichment skipped: {e}")

    step(4, TOTAL, "Building semantic search index")
    if not index_is_built() or rebuild:
        print(f"\n  Building vector index for {wf_count} workflows...")
        print(f"  {DIM}(First run downloads the AI model ~60 MB — takes ~3 minutes){RESET}\n")

        from indexer import build_index
        total_indexed = build_index(rebuild=rebuild)

        if total_indexed == 0:
            error("Index build failed.")
            all_ok = False
        else:
            ok(f"Indexed {total_indexed} workflows")
    else:
        # Quick count check
        from indexer import get_index_stats
        stats = get_index_stats()
        ok(f"Index ready — {stats.get('indexed', '?')} workflows searchable")
        info("Run `python indexer.py --rebuild` to refresh the index")

    return all_ok


# ── Server ────────────────────────────────────────────────────────────────────

def start_server(open_browser: bool = False):
    """Start the FastAPI server."""
    print(f"\n{'─'*54}")
    print(f"{GREEN}{BOLD}  🧠 Starting FlowBrain...{RESET}")
    print(f"{'─'*54}")
    print(f"  Server:    {CYAN}http://{HOST}:{PORT}{RESET}")
    print(f"  API docs:  {CYAN}http://{HOST}:{PORT}/docs{RESET}")
    print(f"  Stop:      {DIM}Ctrl+C{RESET}")
    print(f"{'─'*54}\n")

    # dotenv already loaded at module level — no duplicate load needed

    import uvicorn
    uvicorn.run(
        "server:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="warning",
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    banner()

    parser = argparse.ArgumentParser(
        description="FlowBrain — all-in-one launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py              First-time setup + start server
  python run.py --serve      Just start the server (skip setup checks)
  python run.py --setup      Run setup only (download + index)
  python run.py --rebuild    Rebuild index from scratch, then serve
  python run.py --no-browser Start server without opening browser
        """
    )
    parser.add_argument("--serve",      action="store_true", help="Skip setup, just start server")
    parser.add_argument("--setup",      action="store_true", help="Run setup only, don't start server")
    parser.add_argument("--rebuild",    action="store_true", help="Rebuild index from scratch")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    args = parser.parse_args()

    if args.serve:
        # Just start the server — skip all setup checks
        if not index_is_built():
            warn("Index not found. Run `flowbrain reindex` or `python run.py --setup` first.")
            sys.exit(1)
        start_server(open_browser=not args.no_browser)

    elif args.setup:
        # Run setup but don't start server
        success = run_setup(rebuild=args.rebuild)
        if success:
            print(f"\n{GREEN}{BOLD}✅ Setup complete!{RESET}")
            print(f"\nNow start the server with:  {CYAN}python run.py --serve{RESET}\n")
        else:
            error("Setup encountered errors. Please check the messages above.")
            sys.exit(1)

    else:
        # Full flow: setup + serve
        success = run_setup(rebuild=args.rebuild)
        if not success:
            error("Setup failed. Cannot start server.")
            sys.exit(1)

        print(f"\n{GREEN}{BOLD}✅ Setup complete! Starting server...{RESET}")
        start_server(open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
