"""Tests for config validation and env var overrides."""
import os
from unittest.mock import patch

from omegaconf import OmegaConf

from src.utils.config import validate_config


def _make_config(**overrides):
    """Create a minimal valid config for testing."""
    base = {
        "ai": {"max_concurrent_requests": 10},
        "paths": {"saves": "saves"},
        "game": {"init_npc_num": 12},
        "meta": {"version": "1.0.0"},
        "llm": {"key": "", "base_url": "", "model_name": ""},
    }
    base.update(overrides)
    return OmegaConf.create(base)


def test_valid_config_returns_no_warnings():
    config = _make_config()
    warnings = validate_config(config)
    assert warnings == []


def test_missing_key_produces_warning():
    config = OmegaConf.create({
        "ai": {"max_concurrent_requests": 10},
        "paths": {"saves": "saves"},
        # Missing "game" and "meta"
    })
    warnings = validate_config(config)
    assert any("game.init_npc_num" in w for w in warnings)
    assert any("meta.version" in w for w in warnings)


def test_empty_required_key_produces_warning():
    config = _make_config()
    config.meta.version = ""
    warnings = validate_config(config)
    assert any("meta.version" in w for w in warnings)


def test_empty_optional_keys_no_warning():
    """LLM keys are allowed to be empty (user configures via UI)."""
    config = _make_config()
    config.llm.key = ""
    config.llm.base_url = ""
    warnings = validate_config(config)
    assert warnings == []


def test_env_var_override_llm_key():
    """Test that LLM_API_KEY env var overrides config."""
    with patch.dict(os.environ, {"LLM_API_KEY": "test-key-123"}):
        from src.utils.config import load_config
        config = load_config()
        assert config.llm.key == "test-key-123"


def test_env_var_override_llm_base_url():
    """Test that LLM_BASE_URL env var overrides config."""
    with patch.dict(os.environ, {"LLM_BASE_URL": "https://test.api.com"}):
        from src.utils.config import load_config
        config = load_config()
        assert config.llm.base_url == "https://test.api.com"
