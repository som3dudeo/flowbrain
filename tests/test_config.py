"""Tests for FlowBrain configuration loading."""

import os
import sys
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_defaults():
    """Config should have safe defaults."""
    from flowbrain.config.loader import Config
    cfg = Config()
    assert cfg.host == "127.0.0.1", "Default host must be localhost"
    assert cfg.port == 8001, "Default port must be 8001, not 8000"
    assert cfg.min_autoexec_confidence == 0.85, "Auto-exec threshold must be 0.85"
    assert cfg.default_auto_execute is False, "Auto-execute must default to False"
    assert cfg.open_browser is False, "Browser must not open by default"


def test_config_singleton():
    """get_config() should return the same instance."""
    from flowbrain.config.loader import get_config
    c1 = get_config()
    c2 = get_config()
    assert c1 is c2


def test_config_localhost_bind():
    """Default bind address must be localhost, not 0.0.0.0."""
    from flowbrain.config.loader import get_config
    cfg = get_config()
    assert cfg.host in ("127.0.0.1", "localhost", "::1"), \
        f"Default host must be localhost, got {cfg.host}"


def test_config_safety_thresholds():
    """Safety thresholds must be sane."""
    from flowbrain.config.loader import get_config
    cfg = get_config()
    assert cfg.min_autoexec_confidence >= 0.70, \
        f"Auto-exec threshold dangerously low: {cfg.min_autoexec_confidence}"
    assert cfg.min_preview_confidence >= 0.20, \
        f"Preview threshold too low: {cfg.min_preview_confidence}"
    assert cfg.min_autoexec_confidence > cfg.min_preview_confidence, \
        "Auto-exec must require higher confidence than preview"
