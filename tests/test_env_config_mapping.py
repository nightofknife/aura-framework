from __future__ import annotations

import pytest

from packages.aura_core.config.loader import get_config_value, reset_config_service_cache

pytestmark = pytest.mark.unit


def test_double_underscore_env_segments_preserve_inner_underscores(monkeypatch):
    monkeypatch.setenv("AURA_STATE_STORE__PATH", "./state/test.json")
    monkeypatch.setenv("AURA_API_REMOTE_ENABLED", "1")
    reset_config_service_cache()

    try:
        assert get_config_value("state_store.path") == "./state/test.json"
        assert get_config_value("api.remote.enabled") == "1"
    finally:
        reset_config_service_cache()
