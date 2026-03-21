"""Tests for parameter extraction edge cases."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auto_executor import ParameterExtractor


def test_email_address_is_not_mistaken_for_slack_mention():
    extractor = ParameterExtractor()
    params = extractor.extract("send email to alice@example.com about weekly notes")

    assert params["to_email"] == "alice@example.com"
    assert "slack_at" not in params
