"""
reranker.py — Hybrid re-ranking layer for FlowBrain search results.

The semantic search (ChromaDB + sentence-transformers) is good at broad
intent matching but weak at exact service-name matching.  This module
adds a keyword-based scoring layer that boosts results containing terms
the user actually mentioned.

Strategy:
  1. ChromaDB returns N candidates with semantic cosine scores.
  2. For each candidate, compute a keyword overlap score against the
     user's original query (not the expanded one).
  3. Merge the two signals: final = α*semantic + (1-α)*keyword.
  4. Re-sort and return top_k.

This is a lightweight version of the BM25 + dense retrieval hybrid
approach used in production search systems, optimised for our small
corpus of ~450 workflows where a full BM25 index is overkill.
"""

from __future__ import annotations

import re
import math
from collections import Counter
from dataclasses import dataclass


# ── Tokeniser ───────────────────────────────────────────────────────────────

_STOPWORDS = frozenset({
    "a", "an", "the", "is", "it", "to", "for", "of", "in", "on", "and",
    "or", "my", "me", "i", "we", "our", "when", "that", "this", "with",
    "from", "by", "at", "be", "do", "so", "if", "as", "can", "will",
    "about", "into", "all", "each", "every", "no", "not", "but", "then",
    "than", "up", "out", "just", "now", "how", "what", "who", "which",
    "has", "have", "had", "are", "was", "were", "been", "would", "could",
    "should", "does", "did", "new", "also", "very", "some", "any",
})

_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def tokenise(text: str) -> list[str]:
    """Lower-case, split on non-alphanumeric, remove stopwords."""
    return [
        tok for tok in _SPLIT_RE.split(text.lower())
        if tok and tok not in _STOPWORDS and len(tok) > 1
    ]


# ── Service-name normalisation ──────────────────────────────────────────────
# Users say "email", workflows say "Gmail".  This map lets keyword scoring
# treat them as equivalent.

_ALIASES: dict[str, list[str]] = {
    "email":        ["gmail", "sendgrid", "mailchimp", "outlook", "email", "smtp"],
    "gmail":        ["gmail", "email"],
    "slack":        ["slack"],
    "discord":      ["discord"],
    "telegram":     ["telegram"],
    "notion":       ["notion"],
    "airtable":     ["airtable"],
    "sheet":        ["google sheets", "sheets", "spreadsheet"],
    "sheets":       ["google sheets", "sheets", "spreadsheet"],
    "spreadsheet":  ["google sheets", "sheets", "spreadsheet", "airtable"],
    "trello":       ["trello"],
    "jira":         ["jira"],
    "github":       ["github"],
    "twitter":      ["twitter"],
    "tweet":        ["twitter", "tweet"],
    "x":            ["twitter"],  # "tweet on x"
    "sms":          ["twilio", "sms"],
    "text":         ["twilio", "sms"],
    "webhook":      ["webhook"],
    "rss":          ["rss", "feed"],
    "drive":        ["google drive", "drive"],
    "dropbox":      ["dropbox"],
    "stripe":       ["stripe", "payment"],
    "payment":      ["stripe", "payment"],
    "hubspot":      ["hubspot", "crm"],
    "salesforce":   ["salesforce", "crm"],
    "crm":          ["hubspot", "salesforce", "crm"],
    "openai":       ["openai", "gpt", "ai"],
    "gpt":          ["openai", "gpt", "ai"],
    "ai":           ["openai", "gpt", "ai"],
    "summarize":    ["openai", "gpt", "ai", "summarize", "summary"],
    "summary":      ["openai", "gpt", "ai", "summarize", "summary"],
    "schedule":     ["cron", "schedule", "timer"],
    "cron":         ["cron", "schedule", "timer"],
    "database":     ["mysql", "postgres", "mongodb", "database", "sql"],
    "sql":          ["mysql", "postgres", "sql", "database"],
    "mysql":        ["mysql", "database", "sql"],
    "postgres":     ["postgres", "postgresql", "database", "sql"],
    "mongodb":      ["mongodb", "database", "nosql"],
    "notify":       ["notification", "alert", "message", "notify"],
    "notification": ["notification", "alert", "message", "notify"],
    "alert":        ["notification", "alert", "message"],
    "send":         ["send", "post", "push"],
    "post":         ["send", "post", "push", "publish"],
    "message":      ["message", "send", "chat"],
    "backup":       ["backup", "sync", "copy"],
    "sync":         ["sync", "backup", "mirror"],
    "monitor":      ["monitor", "watch", "check", "alert"],
    "wordpress":    ["wordpress", "blog", "post"],
    "blog":         ["wordpress", "blog"],
}


def expand_query_tokens(tokens: list[str]) -> set[str]:
    """Expand query tokens with known service-name aliases."""
    expanded = set(tokens)
    for tok in tokens:
        if tok in _ALIASES:
            expanded.update(_ALIASES[tok])
    return expanded


# ── Keyword scoring ─────────────────────────────────────────────────────────

def keyword_score(
    query_tokens: set[str],
    doc_name: str,
    doc_desc: str,
    doc_nodes: list[str],
    doc_tags: list[str],
    doc_categories: list[str],
) -> float:
    """
    Compute a 0.0-1.0 keyword overlap score between query terms and a
    workflow's metadata fields.

    Fields are weighted:
      - Name tokens:     weight 3.0  (most specific signal)
      - Node tokens:     weight 2.5  (direct service match)
      - Tag tokens:      weight 2.0
      - Category tokens: weight 1.5
      - Description:     weight 1.0  (least specific)

    Returns a normalised score where 1.0 means every query term matched
    at least one field.
    """
    if not query_tokens:
        return 0.0

    # Build weighted term sets for the document
    name_tokens      = set(tokenise(doc_name))
    node_tokens      = set(tokenise(" ".join(doc_nodes)))
    tag_tokens       = set(tokenise(" ".join(doc_tags)))
    cat_tokens       = set(tokenise(" ".join(doc_categories)))
    desc_tokens      = set(tokenise(doc_desc))

    score = 0.0
    max_score = 0.0

    for qt in query_tokens:
        max_score += 3.0  # best possible per-term weight

        # Check fields in priority order, take the highest weight
        if qt in name_tokens:
            score += 3.0
        elif qt in node_tokens:
            score += 2.5
        elif qt in tag_tokens:
            score += 2.0
        elif qt in cat_tokens:
            score += 1.5
        elif qt in desc_tokens:
            score += 1.0
        # else: no match, 0 points

    if max_score == 0:
        return 0.0

    return score / max_score


# ── Hybrid merger ───────────────────────────────────────────────────────────

# Weight for the semantic (embedding) score vs keyword score.
# 0.65 semantic + 0.35 keyword works well for our use case:
# semantic handles novel phrasings, keywords handle exact service names.
SEMANTIC_WEIGHT = 0.65
KEYWORD_WEIGHT  = 1.0 - SEMANTIC_WEIGHT


@dataclass
class RankedCandidate:
    """A search result with both semantic and keyword scores."""
    workflow_id:    str
    name:           str
    description:    str
    nodes:          list[str]
    categories:     list[str]
    tags:           list[str]
    source_url:     str
    views:          int

    semantic_score: float  # 0-1, from ChromaDB cosine distance
    keyword_score:  float  # 0-1, from keyword_score()
    final_score:    float  # weighted combination


def rerank(
    query: str,
    candidates: list[dict],
    top_k: int = 5,
    semantic_weight: float = SEMANTIC_WEIGHT,
) -> list[RankedCandidate]:
    """
    Re-rank ChromaDB candidates using hybrid semantic + keyword scoring.

    Args:
        query:           The user's original query (not expanded).
        candidates:      List of dicts with keys: workflow_id, name, desc,
                         nodes (str), categories (str), tags (str),
                         source_url, views, confidence (float 0-1).
        top_k:           How many results to return.
        semantic_weight: Weight for the semantic score (default 0.65).

    Returns:
        List of RankedCandidate sorted by final_score descending.
    """
    kw_weight = 1.0 - semantic_weight
    query_tokens_raw = tokenise(query)
    query_tokens = expand_query_tokens(query_tokens_raw)

    ranked = []
    for c in candidates:
        nodes_list = [n.strip() for n in c.get("nodes", "").split(",") if n.strip()]
        tags_list  = [t.strip() for t in c.get("tags", "").split(",") if t.strip()]
        cats_list  = [t.strip() for t in c.get("categories", "").split(",") if t.strip()]

        sem = c.get("confidence", 0.0)
        kw  = keyword_score(
            query_tokens,
            doc_name=c.get("name", ""),
            doc_desc=c.get("desc", ""),
            doc_nodes=nodes_list,
            doc_tags=tags_list,
            doc_categories=cats_list,
        )

        final = sem * semantic_weight + kw * kw_weight

        ranked.append(RankedCandidate(
            workflow_id    = c.get("workflow_id", ""),
            name           = c.get("name", ""),
            description    = c.get("desc", ""),
            nodes          = nodes_list,
            categories     = cats_list,
            tags           = tags_list,
            source_url     = c.get("source_url", ""),
            views          = int(c.get("views", 0)),
            semantic_score = round(sem, 4),
            keyword_score  = round(kw, 4),
            final_score    = round(final, 4),
        ))

    ranked.sort(key=lambda r: r.final_score, reverse=True)
    return ranked[:top_k]
