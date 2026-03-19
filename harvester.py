"""
harvester.py — Step 1: Download n8n workflow templates from n8n.io

This script fetches workflow templates from the public n8n.io API
and saves them as JSON files in ./data/workflows/

Run: python harvester.py
  or: python harvester.py --max 500   (to limit how many you download)
"""

import os
import requests
import json
import time
import argparse
from pathlib import Path

TEMPLATES_DIR = Path("./data/workflows")
N8N_API_BASE  = "https://api.n8n.io"
ROWS_PER_PAGE = 50


def fetch_all_workflows(max_workflows: int = 2000) -> int:
    """Download workflow templates from n8n.io and save as JSON files."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    page           = 0
    total_fetched  = 0
    total_available = None

    print(f"\n🔍 Connecting to n8n.io template library...")

    while total_fetched < max_workflows:
        url    = f"{N8N_API_BASE}/templates/search"
        params = {"rows": ROWS_PER_PAGE, "page": page, "sort": "views:desc"}

        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️  Network error on page {page}: {e}")
            print("     Retrying in 5 seconds...")
            time.sleep(5)
            continue

        workflows = data.get("workflows", [])
        if not workflows:
            print("  No more workflows returned. Done.")
            break

        if total_available is None:
            total_available = data.get("totalWorkflows", "?")
            print(f"   Found {total_available} total workflows on n8n.io")
            print(f"   Downloading up to {max_workflows}...\n")

        for wf in workflows:
            wf_id = str(wf.get("id", "")).strip()
            if not wf_id:
                continue

            # Build a clean, searchable record from the template metadata
            record = {
                "id":          wf_id,
                "name":        wf.get("name", "").strip(),
                "description": wf.get("description", "").strip(),
                "categories":  [c.get("name", "") for c in wf.get("categories", [])],
                "tags":        [t.get("name", "") for t in wf.get("tags", [])],
                "nodes":       _extract_node_types(wf),
                "views":       wf.get("totalViews", 0),
                "source_url":  f"https://n8n.io/workflows/{wf_id}",
            }

            filepath = TEMPLATES_DIR / f"{wf_id}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)

            total_fetched += 1

        bar = _progress_bar(total_fetched, min(max_workflows, total_available or max_workflows))
        print(f"\r  {bar}  {total_fetched} / {min(max_workflows, total_available or '?')} downloaded", end="", flush=True)

        # Stop if we've fetched everything available
        if total_available and total_fetched >= total_available:
            break
        if total_fetched >= max_workflows:
            break

        page += 1
        time.sleep(0.3)   # be polite to the API

    print(f"\n\n✅ Done! Saved {total_fetched} workflows to {TEMPLATES_DIR}/\n")
    return total_fetched


def _extract_node_types(wf: dict) -> list[str]:
    """Pull out the integration names from workflow nodes."""
    nodes = wf.get("nodes", [])
    if not isinstance(nodes, list):
        return []

    seen  = set()
    types = []
    for node in nodes:
        raw = node.get("type", node.get("name", ""))
        # Convert 'n8n-nodes-base.slack' → 'Slack'
        label = raw.split(".")[-1].replace("-", " ").title()
        if label and label not in seen and "trigger" not in label.lower():
            seen.add(label)
            types.append(label)
    return types


def _progress_bar(current: int, total: int, width: int = 30) -> str:
    if total <= 0:
        return "[" + "?" * width + "]"
    filled = int(width * current / total)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def fetch_from_github(repo: str, subpath: str = "") -> int:
    """
    Download n8n workflow JSON files from a GitHub repository.

    Args:
        repo:    GitHub repo in 'owner/name' format (e.g. 'Zie619/n8n-workflows')
        subpath: Subfolder inside the repo to look in (e.g. 'workflows')

    Returns:
        Number of new workflows saved.
    """
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    api_url = f"https://api.github.com/repos/{repo}/contents/{subpath}"
    headers = {"Accept": "application/vnd.github.v3+json"}

    # Add auth token if available (increases rate limit from 60 to 5000/hour)
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    try:
        resp = requests.get(api_url, headers=headers, timeout=15)
        resp.raise_for_status()
        contents = resp.json()
    except Exception as e:
        print(f"  ⚠️  GitHub API error for {repo}: {e}")
        return 0

    if not isinstance(contents, list):
        return 0

    saved = 0
    json_files = [f for f in contents if f.get("name", "").endswith(".json") and f.get("type") == "file"]
    subdirs    = [f for f in contents if f.get("type") == "dir"]

    for file_info in json_files:
        download_url = file_info.get("download_url")
        filename     = file_info.get("name", "")
        if not download_url:
            continue

        # Use a prefixed ID so GitHub workflows don't clash with n8n.io IDs
        wf_id = f"gh_{repo.replace('/','_')}_{filename.replace('.json','')}"
        filepath = TEMPLATES_DIR / f"{wf_id}.json"

        if filepath.exists():
            continue  # skip already downloaded

        try:
            raw = requests.get(download_url, timeout=10)
            raw.raise_for_status()
            wf_data = raw.json()

            # Normalise to our standard record format
            record = {
                "id":          wf_id,
                "name":        wf_data.get("name", filename.replace(".json", "")).strip(),
                "description": wf_data.get("description", "").strip(),
                "categories":  [],
                "tags":        [t.get("name", t) if isinstance(t, dict) else str(t)
                                for t in wf_data.get("tags", [])],
                "nodes":       _extract_node_types(wf_data),
                "views":       0,
                "source_url":  f"https://github.com/{repo}/blob/main/{subpath}/{filename}",
                "source":      f"github:{repo}",
            }

            filepath.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            saved += 1
            time.sleep(0.1)

        except Exception:
            continue

    # Recursively fetch subdirectories (up to 1 level deep)
    for subdir in subdirs[:10]:  # limit to avoid huge repos
        saved += fetch_from_github(repo, subdir.get("path", ""))

    return saved


GITHUB_REPOS = [
    ("Zie619/n8n-workflows",             "workflows"),
    ("Danitilahun/n8n-workflow-templates","workflows"),
]


def fetch_github_supplements(repos: list[tuple] | None = None) -> int:
    """
    Supplement the n8n.io library with workflows from community GitHub repos.
    Call this after fetch_all_workflows() to add more workflows.
    """
    if repos is None:
        repos = GITHUB_REPOS

    print(f"\n📦 Fetching community workflows from GitHub...")
    print(f"   {DIM}Tip: Set GITHUB_TOKEN in .env to increase the rate limit{RESET}\n")

    total = 0
    for repo, path in repos:
        print(f"   {repo}...", end=" ", flush=True)
        n = fetch_from_github(repo, path)
        print(f"{n} new workflows")
        total += n
        time.sleep(1)

    print(f"\n   ✅ {total} additional workflows from GitHub\n")
    return total


DIM = "\033[2m"
RESET = "\033[0m"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download n8n workflow templates")
    parser.add_argument("--max",    type=int, default=2000,
                        help="Maximum workflows from n8n.io (default: 2000)")
    parser.add_argument("--github", action="store_true",
                        help="Also fetch community workflows from GitHub repos")
    args = parser.parse_args()

    total = fetch_all_workflows(args.max)

    if args.github:
        total += fetch_github_supplements()

    print(f"Total workflows downloaded: {total}")
