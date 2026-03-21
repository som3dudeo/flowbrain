"""
embedding.py — Embedding function factory for FlowBrain.

Provides a unified interface for getting an embedding function that works with
ChromaDB.  Prefers the real sentence-transformer model (all-MiniLM-L6-v2) but
falls back to a lightweight character-ngram hash embedding when the model
cannot be downloaded (e.g., offline environments, firewalled networks).

The fallback produces deterministic 384-dim vectors using locality-sensitive
hashing over character n-grams.  It is NOT as good as a real transformer model,
but combined with the hybrid re-ranker (keyword scoring at 35% weight) it
provides usable retrieval quality.  When the real model becomes available,
running `flowbrain reindex` will transparently upgrade to full-quality embeddings.

Usage:
    from embedding import get_embedding_function, EMBEDDING_MODEL, is_using_fallback
    ef = get_embedding_function()
    # ef is a ChromaDB-compatible embedding function
"""

from __future__ import annotations

import hashlib
import re
import warnings
from typing import Optional

import numpy as np

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_cached_ef = None
_using_fallback = False


class HashEmbeddingFunction:
    """
    Deterministic embedding function using character n-gram hashing.
    Produces 384-dimensional unit vectors that capture lexical similarity.
    Compatible with ChromaDB's embedding function interface.
    """

    def __init__(self, dim: int = EMBEDDING_DIM):
        self._dim = dim

    @staticmethod
    def name() -> str:
        return "flowbrain_hash_fallback"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    # ChromaDB >=0.5 calls embed_query for queries and embed_documents for docs
    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def _embed(self, text: str) -> list[float]:
        tokens = re.findall(r"\w+", text.lower())
        vec = np.zeros(self._dim, dtype=np.float64)

        for token in tokens:
            # Unigram hash
            h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[idx] += sign * 1.5  # unigrams get higher weight

            # Character n-gram hashes (bigrams and trigrams)
            for n in range(2, min(len(token) + 1, 5)):
                for i in range(len(token) - n + 1):
                    ngram = token[i : i + n]
                    h = int(hashlib.sha256(ngram.encode()).hexdigest(), 16)
                    idx = h % self._dim
                    sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
                    vec[idx] += sign

        # L2-normalise to unit vector (required for cosine similarity)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm

        return vec.tolist()


def get_embedding_function():
    """
    Return a ChromaDB-compatible embedding function.

    Tries the real sentence-transformer model first.  If that fails (model
    download blocked, no internet, etc.), returns a hash-based fallback and
    prints a warning.
    """
    global _cached_ef, _using_fallback

    if _cached_ef is not None:
        return _cached_ef

    # Try the real model first
    try:
        from chromadb.utils import embedding_functions

        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        # Smoke test — this triggers the actual model download
        ef(["test"])
        _cached_ef = ef
        _using_fallback = False
        return ef
    except Exception as e:
        warnings.warn(
            f"Could not load sentence-transformer model ({type(e).__name__}). "
            f"Using offline hash-based embedding as fallback. "
            f"Search quality will be reduced. "
            f"Run `flowbrain reindex` after resolving network access to upgrade.",
            stacklevel=2,
        )
        _cached_ef = HashEmbeddingFunction(dim=EMBEDDING_DIM)
        _using_fallback = True
        return _cached_ef


def is_using_fallback() -> bool:
    """Return True if the fallback embedding function is in use."""
    return _using_fallback
