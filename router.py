"""
router.py — The semantic matching engine (with hybrid re-ranking)

Given a natural language query from the user, this module searches the
ChromaDB vector index, re-ranks results using keyword overlap scoring,
and returns the best-matching n8n workflows.

The retrieval pipeline:
  1. Expand the query with service-name synonyms (query expansion)
  2. Fetch 3× top_k candidates from ChromaDB (semantic / embedding search)
  3. Re-rank candidates with a hybrid score:
     final = 0.65 × semantic + 0.35 × keyword_overlap
  4. Return top_k results sorted by final score.

This is the core "intelligence" of the whole project.
"""

import re
import chromadb
from pathlib import Path
from dataclasses import dataclass

from embedding import get_embedding_function, is_using_fallback

CHROMA_DB_PATH  = Path("./data/chroma_db")
COLLECTION_NAME = "n8n_workflows"

# Confidence threshold: results below this score are considered poor matches.
# Range: 0.0 (no match) to 1.0 (perfect match). 0.30 is a good starting point.
MIN_CONFIDENCE = 0.30


# ── Query expansion ─────────────────────────────────────────────────────────
# Maps common user phrases to service/node names the embeddings know about.
# This bridges the vocabulary gap between "send email" and "Gmail".
_QUERY_EXPANSIONS: dict[str, str] = {
    r"\bemail\b":           "email Gmail SendGrid message",
    r"\bslack\b":           "Slack message channel notification",
    r"\bdiscord\b":         "Discord message bot notification",
    r"\btelegram\b":        "Telegram message bot chat",
    r"\bnotion\b":          "Notion page database note",
    r"\bspreadsheet\b":     "Google Sheets Airtable spreadsheet",
    r"\bgoogle sheet":      "Google Sheets spreadsheet",
    r"\bairtable\b":        "Airtable base record",
    r"\btrello\b":          "Trello card board task",
    r"\bjira\b":            "Jira issue ticket project",
    r"\bgithub\b":          "GitHub repository issue PR",
    r"\btweet\b":           "Twitter tweet post social media",
    r"\btwitter\b":         "Twitter tweet post social media",
    r"\b(?:on|from|to)\s+x\b":  "Twitter tweet post social media",
    r"\bsms\b":             "Twilio SMS text message",
    r"\btext message\b":    "Twilio SMS text message",
    r"\bwebhook\b":         "Webhook HTTP trigger callback",
    r"\bcron\b":            "Cron schedule timer recurring",
    r"\bschedule\b":        "Cron schedule timer recurring",
    r"\brss\b":             "RSS feed news article",
    r"\bai\b":              "OpenAI GPT AI language model",
    r"\bgpt\b":             "OpenAI GPT AI language model",
    r"\bchat\b":            "chat message bot conversation",
    r"\bnotif":             "notification alert message push",
    r"\bcrm\b":             "CRM HubSpot Salesforce contact deal",
    r"\bpayment\b":         "Stripe payment invoice charge",
    r"\bfile\b":            "file upload download Google Drive Dropbox S3",
    r"\bdatabase\b":        "database MySQL Postgres MongoDB SQL query",
    r"\bsql\b":             "database MySQL Postgres SQL query",
    r"\bsummar":            "summarize summary AI GPT OpenAI",
    r"\bmonitor\b":         "monitor watch check alert RSS",
    r"\bbackup\b":          "backup sync copy Google Drive Dropbox S3",
    r"\bblog\b":            "WordPress blog post publish",
    r"\bsend\b":            "send message post push",
    r"\bpost\b":            "post send publish message",
}


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
    confidence:   float     # 0.0 – 1.0, higher is better (hybrid score)
    views:        int


class WorkflowRouter:
    """
    Loads the ChromaDB vector index and routes natural language queries
    to the most semantically relevant n8n workflows using hybrid retrieval.

    Usage:
        router = WorkflowRouter()
        results = router.search("notify my team on Slack when a form is submitted")
        for r in results:
            print(r.name, r.confidence)
    """

    def __init__(self):
        self._collection = None
        self._client     = None
        self._embed_fn   = None
        self._ready      = False

    def load(self) -> bool:
        """Load the vector index. Returns True if successful."""
        if not CHROMA_DB_PATH.exists():
            return False
        ok = self._reload_collection()
        if ok and is_using_fallback():
            print("[Router] Using fallback embeddings — search quality reduced.")
            print("[Router] Run `flowbrain reindex` with internet to upgrade.")
        return ok

    def _reload_collection(self) -> bool:
        """Reload the Chroma collection handle (needed after index rebuilds)."""
        if not CHROMA_DB_PATH.exists():
            self._ready = False
            self._collection = None
            return False
        try:
            if self._embed_fn is None:
                self._embed_fn = get_embedding_function()
            self._client = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
            self._collection = self._client.get_collection(
                name=COLLECTION_NAME,
                embedding_function=self._embed_fn,
            )
            self._ready = True
            return True
        except Exception as e:
            self._ready = False
            self._collection = None
            print(f"[Router] Failed to load index: {e}")
            return False

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def workflow_count(self) -> int:
        if not self._ready:
            return 0
        try:
            return self._collection.count()
        except Exception:
            if self._reload_collection():
                try:
                    return self._collection.count()
                except Exception:
                    pass
            return 0

    def search(self, query: str, top_k: int = 5) -> list[WorkflowMatch]:
        """
        Search for the best matching workflows for a natural language query.

        Uses a hybrid retrieval approach:
          1. Query expansion adds service-name synonyms.
          2. ChromaDB semantic search returns 3× candidates.
          3. Hybrid re-ranking merges semantic + keyword scores.

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

        # ── Step 1: Expand query ────────────────────────────────────────
        expanded_query = _expand_query(query)

        # ── Step 2: Fetch candidates from ChromaDB ──────────────────────
        fetch_k = min(top_k * 3, self.workflow_count) if self.workflow_count > 0 else top_k

        try:
            results = self._collection.query(
                query_texts=[expanded_query],
                n_results=max(fetch_k, 1),
                include=["metadatas", "distances", "documents"]
            )
        except Exception:
            if not self._reload_collection():
                raise RuntimeError("Router index became unavailable. Run `flowbrain reindex`.")
            results = self._collection.query(
                query_texts=[expanded_query],
                n_results=max(fetch_k, 1),
                include=["metadatas", "distances", "documents"]
            )

        ids       = results.get("ids",       [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        # Build candidate dicts for the re-ranker
        candidates = []
        for wf_id, meta, dist in zip(ids, metadatas, distances):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            semantic_confidence = max(0.0, 1.0 - (dist / 2.0))

            if semantic_confidence < MIN_CONFIDENCE * 0.7:
                # Skip very poor semantic matches (below 70% of threshold)
                continue

            candidates.append({
                "workflow_id":  wf_id,
                "name":         meta.get("name", "Unknown Workflow"),
                "desc":         meta.get("desc", ""),
                "nodes":        meta.get("nodes", ""),
                "categories":   meta.get("categories", ""),
                "tags":         meta.get("tags", ""),
                "source_url":   meta.get("source_url", f"https://n8n.io/workflows/{wf_id}"),
                "views":        int(meta.get("views", 0)),
                "confidence":   semantic_confidence,
            })

        if not candidates:
            return []

        # ── Step 3: Hybrid re-ranking ───────────────────────────────────
        from reranker import rerank

        ranked = rerank(query, candidates, top_k=top_k)

        # ── Step 4: Convert to WorkflowMatch objects ────────────────────
        matches = []
        for r in ranked:
            if r.final_score < MIN_CONFIDENCE:
                continue

            matches.append(WorkflowMatch(
                workflow_id  = r.workflow_id,
                name         = r.name,
                description  = r.description,
                nodes        = r.nodes,
                categories   = r.categories,
                tags         = r.tags,
                source_url   = r.source_url,
                confidence   = round(r.final_score, 3),
                views        = r.views,
            ))

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


# ── Query expansion helpers ──────────────────────────────────────────────────

def _expand_query(query: str) -> str:
    """
    Enrich a user query with service-specific synonyms.

    For example, "send email to bob" becomes
    "send email to bob email Gmail SendGrid message" — this gives the
    embedding model more context to match against indexed documents.
    """
    additions = set()
    q_lower = query.lower()
    for pattern, expansion in _QUERY_EXPANSIONS.items():
        if re.search(pattern, q_lower):
            for word in expansion.split():
                if word.lower() not in q_lower:
                    additions.add(word)
    if additions:
        return query + " " + " ".join(sorted(additions))
    return query


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
            print(f"       Confidence : {int(r.confidence*100)}%")
            print(f"       Nodes      : {', '.join(r.nodes[:5]) or 'N/A'}")
            print(f"       URL        : {r.source_url}")
            if r.description:
                preview = r.description[:120] + ("..." if len(r.description) > 120 else "")
                print(f"       Description: {preview}")
    print(f"{'─'*60}\n")
