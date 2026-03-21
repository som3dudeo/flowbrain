"""Tests for the embedding fallback system."""

import os
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from embedding import HashEmbeddingFunction, EMBEDDING_DIM


class TestHashEmbeddingFunction:
    def setup_method(self):
        self.ef = HashEmbeddingFunction(dim=EMBEDDING_DIM)

    def test_produces_correct_dimensionality(self):
        """Embeddings must be 384-dimensional."""
        vecs = self.ef(["hello world"])
        assert len(vecs) == 1
        assert len(vecs[0]) == EMBEDDING_DIM

    def test_produces_unit_vectors(self):
        """Embeddings must be L2-normalized to unit length."""
        vecs = self.ef(["test sentence with several words"])
        norm = np.linalg.norm(vecs[0])
        assert abs(norm - 1.0) < 1e-6, f"Expected unit vector, got norm={norm}"

    def test_deterministic(self):
        """Same input must always produce the same vector."""
        v1 = self.ef(["send slack message"])[0]
        v2 = self.ef(["send slack message"])[0]
        assert v1 == v2

    def test_different_inputs_produce_different_vectors(self):
        """Different inputs should produce meaningfully different vectors."""
        v1 = np.array(self.ef(["send email to bob"])[0])
        v2 = np.array(self.ef(["create jira ticket"])[0])
        cosine_sim = np.dot(v1, v2)  # both unit vectors
        assert cosine_sim < 0.95, f"Vectors too similar: cosine_sim={cosine_sim}"

    def test_similar_inputs_more_similar(self):
        """Semantically related inputs should be more similar than unrelated ones."""
        v_slack = np.array(self.ef(["send slack message"])[0])
        v_discord = np.array(self.ef(["send discord message"])[0])
        v_database = np.array(self.ef(["query postgres database"])[0])

        sim_related = np.dot(v_slack, v_discord)
        sim_unrelated = np.dot(v_slack, v_database)
        assert sim_related > sim_unrelated, (
            f"Related pair ({sim_related:.3f}) should be more similar "
            f"than unrelated pair ({sim_unrelated:.3f})"
        )

    def test_batch_processing(self):
        """Multiple inputs should be processed correctly."""
        inputs = ["hello", "world", "foo bar baz"]
        vecs = self.ef(inputs)
        assert len(vecs) == 3
        for v in vecs:
            assert len(v) == EMBEDDING_DIM

    def test_empty_string_produces_zero_vector(self):
        """Empty string should produce a zero vector (no tokens to hash)."""
        vecs = self.ef([""])
        # Zero vector can't be normalized, so it stays zero
        norm = np.linalg.norm(vecs[0])
        assert norm < 1e-6

    def test_name_method(self):
        """ChromaDB requires a .name() method."""
        assert self.ef.name() == "flowbrain_hash_fallback"

    def test_embed_query_interface(self):
        """ChromaDB >=0.5 calls embed_query for queries."""
        vecs = self.ef.embed_query(["test query"])
        assert len(vecs) == 1
        assert len(vecs[0]) == EMBEDDING_DIM

    def test_embed_documents_interface(self):
        """ChromaDB >=0.5 calls embed_documents for docs."""
        vecs = self.ef.embed_documents(["doc one", "doc two"])
        assert len(vecs) == 2
