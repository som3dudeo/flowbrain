"""
router.py — The semantic matching engine

Given a natural language query from the user, this module searches the
ChromaDB vector index and returns the best-matching n8n workflows.

This is the core "intelligence" of the whole project.
"""

import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path
from dataclasses import dataclass

CHROMA_DB_PATH  = Path("./data/chroma_db")
COLLECTION_NAME = "n8n_workflows"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Confidence threshold: results below this score are considered poor matches.
# Range: 0.0 (no match) to 1.0 (perfect match). 0.30 is a good starting point.
MIN_CONFIDENCE = 0.30


@dataclass
class WorkflowMatch:
    """A single workflow result returned by the router."""
    workflow_id:  str
    name:         str
    description:  str
    nodes:        list[str]
    categories:   list[str]
    tags:         list[str]
    source_url:   str
    confidence:   float     # 0.0 – 1.0, higher is better
    views:        int


class WorkflowRouter:
    """
    Loads the ChromaDB vector index and routes natural language queries
    to the most semantically relevant n8n workflows.

    Usage:
        router = WorkflowRouter()
        results = router.search("notify my team on Slack when a form is submitted")
        for r in results:
            print(r.name, r.confidence)
    """

    def __init__(self):
        self._collection = None
        self._ready      = False

    def load(self) -> bool:
        """Load the vector index. Returns True if successful."""
        if not CHROMA_DB_PATH.exists():
            return False
        try:
            embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=EMBEDDING_MODEL
            )
            client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
            self._collection = client.get_collection(
                name=COLLECTION_NAME,
                embedding_function=embed_fn
            )
            self._ready = True
            return True
        except Exception as e:
            print(f"[Router] Failed to load index: {e}")
            return False

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def workflow_count(self) -> int:
        if not self._ready:
            return 0
        return self._collection.count()

    def search(self, query: str, top_k: int = 5) -> list[WorkflowMatch]:
        """
        Search for the best matching workflows for a natural language query.

        Args:
            query:  What the user wants to do, in plain English.
            top_k:  How many results to return (default 5).

        Returns:
            List of WorkflowMatch objects, sorted by confidence (best first).
        """
        if not self._ready:
            raise RuntimeError("Router is not loaded. Call .load() first.")
        if not query or not query.strip():
            return []

        query = query.strip()

        results = self._collection.query(
            query_texts=[query],
            n_results=min(top_k, self.workflow_count),
            include=["metadatas", "distances", "documents"]
        )

        matches = []

        ids       = results.get("ids",       [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for wf_id, meta, dist in zip(ids, metadatas, distances):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to a 0-1 confidence score (1 = perfect match)
            confidence = max(0.0, 1.0 - (dist / 2.0))

            if confidence < MIN_CONFIDENCE:
                continue

            # Parse node types from the stored string
            nodes_str = meta.get("nodes", "")
            nodes = [n.strip() for n in nodes_str.split(",") if n.strip()]

            categories_str = meta.get("categories", "")
            categories = [c.strip() for c in categories_str.split(",") if c.strip()]

            tags_str = meta.get("tags", "")
            tags = [t.strip() for t in tags_str.split(",") if t.strip()]

            matches.append(WorkflowMatch(
                workflow_id  = wf_id,
                name         = meta.get("name", "Unknown Workflow"),
                description  = meta.get("desc", ""),
                nodes        = nodes,
                categories   = categories,
                tags         = tags,
                source_url   = meta.get("source_url", f"https://n8n.io/workflows/{wf_id}"),
                confidence   = round(confidence, 3),
                views        = int(meta.get("views", 0)),
            ))

        # Sort by confidence descending
        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches

    def search_dict(self, query: str, top_k: int = 5) -> list[dict]:
        """Same as search(), but returns plain dicts (for JSON serialization)."""
        return [
            {
                "workflow_id":  m.workflow_id,
                "name":         m.name,
                "description":  m.description,
                "nodes":        m.nodes,
                "categories":   m.categories,
                "tags":         m.tags,
                "source_url":   m.source_url,
                "confidence":   m.confidence,
                "views":        m.views,
                "confidence_pct": f"{int(m.confidence * 100)}%",
            }
            for m in self.search(query, top_k)
        ]


# Singleton instance — shared across the FastAPI app
_router_instance: WorkflowRouter | None = None


def get_router() -> WorkflowRouter:
    """Get (or lazily initialize) the shared router instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = WorkflowRouter()
        _router_instance.load()
    return _router_instance


# ── Quick CLI test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "send a Slack message when a form is submitted"
    print(f'\n🔍 Searching for: "{query}"\n')

    router = WorkflowRouter()
    if not router.load():
        print("❌ Index not found. Run `python indexer.py` first.")
        sys.exit(1)

    print(f"   Index contains {router.workflow_count} workflows\n")

    results = router.search(query, top_k=5)

    if not results:
        print("No confident matches found. Try a different query.")
    else:
        for i, r in enumerate(results, 1):
            print(f"{'─'*60}")
            print(f"  #{i}  {r.name}")
            print(f"       Confidence : {r.confidence_pct if hasattr(r, 'confidence_pct') else f'{int(r.confidence*100)}%'}")
            print(f"       Nodes      : {', '.join(r.nodes[:5]) or 'N/A'}")
            print(f"       URL        : {r.source_url}")
            if r.description:
                preview = r.description[:120] + ("..." if len(r.description) > 120 else "")
                print(f"       Description: {preview}")
    print(f"{'─'*60}\n")
