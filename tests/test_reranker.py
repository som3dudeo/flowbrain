"""
Tests for the hybrid re-ranking system.

These tests verify that:
1. Keyword scoring correctly weights service-name matches
2. Query expansion enriches vague terms
3. Hybrid re-ranking reorders results so service-relevant workflows
   rank higher than semantically-similar but irrelevant ones
4. Alias expansion works (e.g., "email" matches "Gmail")
"""

import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reranker import (
    tokenise,
    expand_query_tokens,
    keyword_score,
    rerank,
    RankedCandidate,
)
from router import _expand_query


# ── Tokeniser tests ────────────────────────────────────────────────────────

class TestTokenise:
    def test_basic(self):
        tokens = tokenise("Send a Slack message to #general")
        assert "send" in tokens
        assert "slack" in tokens
        assert "message" in tokens
        # Stopwords removed
        assert "a" not in tokens
        assert "to" not in tokens

    def test_removes_short_tokens(self):
        tokens = tokenise("I x y go")
        assert "x" not in tokens
        assert "y" not in tokens
        assert "go" in tokens

    def test_splits_on_special_chars(self):
        tokens = tokenise("email@user.com — Gmail/Outlook!")
        assert "email" in tokens
        assert "gmail" in tokens
        assert "outlook" in tokens


# ── Alias expansion tests ──────────────────────────────────────────────────

class TestAliasExpansion:
    def test_email_expands_to_gmail(self):
        tokens = tokenise("send email")
        expanded = expand_query_tokens(tokens)
        assert "gmail" in expanded
        assert "sendgrid" in expanded

    def test_tweet_expands_to_twitter(self):
        tokens = tokenise("tweet something")
        expanded = expand_query_tokens(tokens)
        assert "twitter" in expanded

    def test_sms_expands_to_twilio(self):
        tokens = tokenise("send sms")
        expanded = expand_query_tokens(tokens)
        assert "twilio" in expanded

    def test_ai_expands_to_openai(self):
        tokens = tokenise("ai summarize")
        expanded = expand_query_tokens(tokens)
        assert "openai" in expanded
        assert "gpt" in expanded

    def test_unknown_word_passes_through(self):
        tokens = tokenise("frobnicator")
        expanded = expand_query_tokens(tokens)
        assert "frobnicator" in expanded


# ── Keyword scoring tests ──────────────────────────────────────────────────

class TestKeywordScore:
    def test_slack_query_matches_slack_workflow(self):
        """A query about Slack should score high for a Slack workflow."""
        query_tokens = expand_query_tokens(tokenise("send slack message"))
        score = keyword_score(
            query_tokens,
            doc_name="Post Slack notification from Typeform",
            doc_desc="Sends a message to Slack when a form is submitted",
            doc_nodes=["Slack", "Typeform Trigger", "Set"],
            doc_tags=["notification"],
            doc_categories=["Communication"],
        )
        assert score > 0.3, f"Slack workflow should score > 0.3, got {score}"

    def test_slack_query_low_for_gmail_workflow(self):
        """A query about Slack should score low for a Gmail workflow."""
        query_tokens = expand_query_tokens(tokenise("send slack message"))
        score = keyword_score(
            query_tokens,
            doc_name="Forward Gmail to Notion",
            doc_desc="Saves Gmail emails as Notion pages",
            doc_nodes=["Gmail", "Notion", "Set"],
            doc_tags=["email"],
            doc_categories=["Productivity"],
        )
        # "message" and "send" may match weakly in desc, but "slack" won't
        assert score < 0.4, f"Gmail workflow should score < 0.4 for Slack query, got {score}"

    def test_email_query_matches_gmail_via_alias(self):
        """'email' should match Gmail workflows through alias expansion."""
        query_tokens = expand_query_tokens(tokenise("send email"))
        score = keyword_score(
            query_tokens,
            doc_name="Send Gmail notification",
            doc_desc="Sends an automated email via Gmail",
            doc_nodes=["Gmail", "Cron Trigger"],
            doc_tags=["email", "notification"],
            doc_categories=["Communication"],
        )
        assert score > 0.25, f"Gmail workflow should score > 0.25 for 'email' query, got {score}"

    def test_empty_query_returns_zero(self):
        score = keyword_score(
            set(),
            doc_name="Anything",
            doc_desc="Whatever",
            doc_nodes=["Slack"],
            doc_tags=[],
            doc_categories=[],
        )
        assert score == 0.0

    def test_relevant_workflow_scores_higher_than_irrelevant(self):
        """A Slack workflow should always score higher than an unrelated workflow for a Slack query."""
        query_tokens = expand_query_tokens(tokenise("send slack message"))
        slack_score = keyword_score(
            query_tokens,
            doc_name="Post Slack notification from Typeform",
            doc_desc="Sends a message to Slack when a form is submitted",
            doc_nodes=["Slack", "Typeform Trigger", "Set"],
            doc_tags=["notification"],
            doc_categories=["Communication"],
        )
        unrelated_score = keyword_score(
            query_tokens,
            doc_name="Backup Google Sheets to Dropbox",
            doc_desc="Weekly backup of spreadsheet data",
            doc_nodes=["Google Sheets", "Dropbox", "Cron"],
            doc_tags=["backup"],
            doc_categories=["Data"],
        )
        assert slack_score > unrelated_score * 2, \
            f"Slack score ({slack_score}) should be much higher than unrelated ({unrelated_score})"

    def test_name_match_scores_highest(self):
        """A match in the name field should score higher than in description."""
        tokens = expand_query_tokens(tokenise("jira"))
        name_score = keyword_score(
            tokens,
            doc_name="Create Jira ticket",
            doc_desc="Workflow automation",
            doc_nodes=["Set"],
            doc_tags=[],
            doc_categories=[],
        )
        desc_score = keyword_score(
            tokens,
            doc_name="Generic workflow",
            doc_desc="Create Jira ticket from input",
            doc_nodes=["Set"],
            doc_tags=[],
            doc_categories=[],
        )
        assert name_score > desc_score


# ── Re-ranking integration tests ──────────────────────────────────────────

class TestRerank:
    """Test that rerank() correctly re-orders candidates."""

    def _make_candidate(self, name, nodes, confidence, desc="", tags="", categories=""):
        return {
            "workflow_id": f"wf_{name.lower().replace(' ','_')[:20]}",
            "name": name,
            "desc": desc,
            "nodes": nodes,
            "categories": categories,
            "tags": tags,
            "source_url": "https://example.com",
            "views": 100,
            "confidence": confidence,
        }

    def test_rerank_promotes_relevant_service(self):
        """
        Given two candidates with similar semantic scores,
        the one matching the query's service should rank first.
        """
        candidates = [
            self._make_candidate(
                "AI Data Processing Pipeline",
                "OpenAI, Set, Function",
                0.72,
                desc="Process data with AI",
            ),
            self._make_candidate(
                "Post Slack notification",
                "Slack, Webhook, Set",
                0.68,
                desc="Send a message to a Slack channel",
                tags="notification, slack",
            ),
        ]
        results = rerank("send slack message", candidates, top_k=2)
        assert results[0].name == "Post Slack notification", \
            f"Slack workflow should rank first, got: {results[0].name}"

    def test_rerank_email_promotes_gmail(self):
        """'send email' should promote Gmail workflows over unrelated ones."""
        candidates = [
            self._make_candidate(
                "Sync RSS to Notion",
                "RSS, Notion, Set",
                0.75,
                desc="Saves RSS feed items to Notion database",
            ),
            self._make_candidate(
                "Send automated Gmail",
                "Gmail, Cron, Set",
                0.65,
                desc="Send automated email via Gmail on a schedule",
                tags="email, notification",
            ),
        ]
        results = rerank("send email to john", candidates, top_k=2)
        assert results[0].name == "Send automated Gmail", \
            f"Gmail workflow should rank first for 'send email', got: {results[0].name}"

    def test_rerank_tweet_promotes_twitter(self):
        """'tweet on x' should promote Twitter workflows."""
        candidates = [
            self._make_candidate(
                "Google Sheets Backup",
                "Google Sheets, Google Drive, Cron",
                0.70,
            ),
            self._make_candidate(
                "Auto-post tweet from RSS",
                "Twitter, RSS, Set",
                0.60,
                desc="Post a tweet when new RSS item appears",
                tags="social media, twitter",
            ),
        ]
        results = rerank("tweet on x", candidates, top_k=2)
        assert results[0].name == "Auto-post tweet from RSS", \
            f"Twitter workflow should rank first for 'tweet on x', got: {results[0].name}"

    def test_rerank_preserves_order_when_no_keyword_signal(self):
        """When query has no strong keyword match, semantic order is preserved."""
        candidates = [
            self._make_candidate("Workflow A", "Set, If, Code", 0.80),
            self._make_candidate("Workflow B", "Set, If, Code", 0.60),
        ]
        results = rerank("do something interesting", candidates, top_k=2)
        assert results[0].name == "Workflow A"
        assert results[1].name == "Workflow B"

    def test_rerank_respects_top_k(self):
        """Should return at most top_k results."""
        candidates = [
            self._make_candidate(f"Workflow {i}", "Set", 0.5 + i*0.05)
            for i in range(10)
        ]
        results = rerank("test", candidates, top_k=3)
        assert len(results) <= 3

    def test_rerank_returns_ranked_candidates(self):
        """Return type should be list of RankedCandidate."""
        candidates = [self._make_candidate("Test", "Slack", 0.7)]
        results = rerank("slack", candidates, top_k=1)
        assert len(results) == 1
        assert isinstance(results[0], RankedCandidate)
        assert results[0].semantic_score == 0.7
        assert results[0].keyword_score > 0  # "slack" in nodes
        assert results[0].final_score > 0


# ── Query expansion tests ──────────────────────────────────────────────────

class TestQueryExpansion:
    def test_email_expanded(self):
        expanded = _expand_query("send email to bob")
        low = expanded.lower()
        assert "gmail" in low

    def test_tweet_on_x_expanded(self):
        expanded = _expand_query("tweet on x")
        low = expanded.lower()
        assert "twitter" in low

    def test_slack_expanded(self):
        expanded = _expand_query("send slack message")
        low = expanded.lower()
        assert "channel" in low or "notification" in low

    def test_no_expansion_for_unknown(self):
        original = "frobnicator blip"
        expanded = _expand_query(original)
        assert expanded == original  # nothing to expand

    def test_summary_expanded(self):
        expanded = _expand_query("summarize my documents")
        low = expanded.lower()
        assert "openai" in low or "gpt" in low
