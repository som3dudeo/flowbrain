"""
indexer.py — Step 2: Build the semantic vector index from your downloaded workflows

Reads all JSON files from ./data/workflows/, creates vector embeddings from
their names + descriptions + node types, and stores everything in ChromaDB.

Run: python indexer.py
  or: python indexer.py --rebuild   (wipes existing index and rebuilds from scratch)

This only needs to run once (or when you add new workflows).
It takes 2-5 minutes for 2,000 workflows on a normal laptop.
"""

import json
import argparse
import shutil
from pathlib import Path

import chromadb
from tqdm import tqdm

from embedding import get_embedding_function, is_using_fallback, EMBEDDING_MODEL


WORKFLOWS_DIR  = Path("./data/workflows")
CHROMA_DB_PATH = Path("./data/chroma_db")
COLLECTION_NAME = "n8n_workflows"


def build_index(rebuild: bool = False) -> int:
    """
    Load all workflow JSON files, embed them, and store in ChromaDB.
    Returns the total number of workflows indexed.
    """
    if not WORKFLOWS_DIR.exists() or not any(WORKFLOWS_DIR.glob("*.json")):
        print("❌ No workflows found in ./data/workflows/")
        print("   Please run `python harvester.py` first.")
        return 0

    # If rebuilding, wipe the old index
    if rebuild and CHROMA_DB_PATH.exists():
        print("🗑️  Removing existing index for rebuild...")
        shutil.rmtree(CHROMA_DB_PATH)

    CHROMA_DB_PATH.mkdir(parents=True, exist_ok=True)

    print(f"\n🧠 Loading embedding model: {EMBEDDING_MODEL}")
    print("   (First run downloads ~60 MB — subsequent runs are instant)\n")

    embed_fn = get_embedding_function()
    if is_using_fallback():
        print("   ⚠  Using offline fallback embeddings (reduced quality).")
        print("      Run `flowbrain reindex` with internet access to upgrade.\n")

    client     = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"}
    )

    # Find which workflows are already indexed (for incremental updates)
    already_indexed = set(collection.get()["ids"])

    # Load all JSON files
    all_files = sorted(WORKFLOWS_DIR.glob("*.json"))
    new_files  = [f for f in all_files if f.stem not in already_indexed]

    if not new_files:
        total = collection.count()
        print(f"✅ Index is up to date — {total} workflows already indexed.")
        return total

    print(f"📚 Found {len(all_files)} workflows  ({len(new_files)} new to index)")
    print(f"   Indexing in batches of 100...\n")

    # Process in batches of 100 (ChromaDB recommends batching)
    BATCH_SIZE = 100
    indexed    = 0

    for batch_start in tqdm(range(0, len(new_files), BATCH_SIZE), unit="batch"):
        batch_files = new_files[batch_start : batch_start + BATCH_SIZE]

        ids       = []
        documents = []
        metadatas = []

        for filepath in batch_files:
            try:
                wf = json.loads(filepath.read_text(encoding="utf-8"))
            except Exception:
                continue

            wf_id = str(wf.get("id", filepath.stem))
            name  = wf.get("name", "").strip()
            desc  = wf.get("description", "").strip()
            nodes = ", ".join(wf.get("nodes", []))
            cats  = ", ".join(wf.get("categories", []))
            tags  = ", ".join(wf.get("tags", []))

            # The "document" is what gets embedded — pack in all searchable info
            document = _build_document(name, desc, nodes, cats, tags)

            # Metadata is stored alongside the vector for retrieval
            meta = {
                "name":       name[:500],
                "desc":       desc[:1000],
                "nodes":      nodes[:500],
                "categories": cats[:200],
                "tags":       tags[:200],
                "views":      int(wf.get("views", 0)),
                "source_url": wf.get("source_url", f"https://n8n.io/workflows/{wf_id}"),
            }

            ids.append(wf_id)
            documents.append(document)
            metadatas.append(meta)

        if ids:
            collection.add(ids=ids, documents=documents, metadatas=metadatas)
            indexed += len(ids)

    total = collection.count()
    print(f"\n✅ Indexing complete!")
    print(f"   {indexed} new workflows added  |  {total} total in index\n")
    return total


def _build_document(name: str, desc: str, nodes: str, cats: str, tags: str) -> str:
    """
    Combine all workflow metadata into a single searchable text string.
    The quality of this string directly determines search accuracy.

    Strategy: repeat the name (most important signal), expand node names into
    natural-language phrases so the embedding captures intent, and include all
    available metadata.  The resulting document reads like a mini-article so the
    sentence-transformer produces a richer, more query-aligned embedding.
    """
    parts = []

    # Name appears twice: once as a title, once inside a sentence.  This
    # gives the title terms higher weight in the embedding.
    if name:
        parts.append(name)
        parts.append(f"This automation workflow is called \"{name}\".")

    if desc:
        parts.append(desc)

    if nodes:
        # Turn comma-separated nodes into an intent-style sentence.
        node_list = [n.strip() for n in nodes.split(",") if n.strip()]
        expanded = _expand_node_names(node_list)
        parts.append(f"Services and integrations used: {', '.join(expanded)}.")
        # Also add plain node list for exact-match queries
        parts.append(f"Nodes: {nodes}")

    if cats:
        parts.append(f"Categories: {cats}")

    if tags:
        parts.append(f"Tags: {tags}")

    return "\n".join(parts)


# Map common n8n node type names to richer natural-language synonyms so the
# embedding captures user intent (people say "send email" not "Gmail node").
_NODE_SYNONYMS: dict[str, str] = {
    "Gmail":             "Gmail email send receive",
    "Slack":             "Slack message channel notification",
    "Discord":           "Discord message bot notification",
    "Telegram":          "Telegram message bot chat",
    "Notion":            "Notion page database note",
    "Airtable":          "Airtable base record spreadsheet",
    "Google Sheets":     "Google Sheets spreadsheet row cell",
    "Google Drive":      "Google Drive file upload download",
    "Dropbox":           "Dropbox file cloud storage",
    "Trello":            "Trello card board task",
    "Jira":              "Jira issue ticket project",
    "Linear":            "Linear issue task project",
    "GitHub":            "GitHub repository issue pull request",
    "Twitter":           "Twitter tweet post social media",
    "WordPress":         "WordPress blog post publish",
    "HubSpot":           "HubSpot CRM contact deal",
    "Salesforce":        "Salesforce CRM lead opportunity",
    "Stripe":            "Stripe payment invoice charge",
    "Twilio":            "Twilio SMS text message phone",
    "SendGrid":          "SendGrid email send",
    "Mailchimp":         "Mailchimp email campaign newsletter",
    "OpenAI":            "OpenAI GPT AI language model",
    "HTTP Request":      "HTTP API request call webhook",
    "Webhook":           "Webhook trigger HTTP callback",
    "Cron":              "Cron schedule timer recurring",
    "RSS":               "RSS feed news article",
    "MySQL":             "MySQL database SQL query",
    "Postgres":          "PostgreSQL database SQL query",
    "MongoDB":           "MongoDB database document NoSQL",
    "Redis":             "Redis cache key-value store",
    "S3":                "AWS S3 file storage bucket",
}


def _expand_node_names(nodes: list[str]) -> list[str]:
    """Return node names enriched with synonyms where known."""
    out = []
    for node in nodes:
        syn = _NODE_SYNONYMS.get(node)
        if syn:
            out.append(syn)
        else:
            out.append(node)
    return out


def get_index_stats() -> dict:
    """Return statistics about the current index."""
    if not CHROMA_DB_PATH.exists():
        return {"indexed": 0, "status": "not_built"}
    try:
        client     = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        collection = client.get_collection(COLLECTION_NAME)
        return {"indexed": collection.count(), "status": "ready"}
    except Exception:
        return {"indexed": 0, "status": "error"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the n8n workflow semantic index")
    parser.add_argument("--rebuild", action="store_true",
                        help="Wipe existing index and rebuild from scratch")
    args = parser.parse_args()
    build_index(rebuild=args.rebuild)
