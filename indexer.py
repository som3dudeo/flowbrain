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
from chromadb.utils import embedding_functions
from tqdm import tqdm


WORKFLOWS_DIR  = Path("./data/workflows")
CHROMA_DB_PATH = Path("./data/chroma_db")
COLLECTION_NAME = "n8n_workflows"

# The embedding model — runs locally, no API key needed, ~60 MB download on first run
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


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

    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )

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
    """
    parts = []
    if name:
        parts.append(f"Workflow: {name}")
    if desc:
        parts.append(f"Description: {desc}")
    if nodes:
        parts.append(f"Integrations used: {nodes}")
    if cats:
        parts.append(f"Categories: {cats}")
    if tags:
        parts.append(f"Tags: {tags}")
    return "\n".join(parts)


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
