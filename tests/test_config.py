"""Tests for configuration module."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest


class TestConfigDefaults:
    """Test default configuration values."""

    def test_default_paths_exist(self):
        from fitbit_mcp.config import CONFIG_DIR, DB_PATH
        # Defaults use XDG-compatible locations under the user home directory
        assert isinstance(CONFIG_DIR, Path)
        assert isinstance(DB_PATH, Path)
        assert CONFIG_DIR.name == "fitbit-mcp"
        assert str(CONFIG_DIR).startswith(str(Path.home()))
        assert DB_PATH.name == "fitbit.db"
        assert str(DB_PATH).startswith(str(Path.home()))

    def test_api_constants(self):
        from fitbit_mcp.config import (
            FITBIT_API_BASE, FITBIT_AUTH_URL, FITBIT_TOKEN_URL,
            FITBIT_SCOPES, FITBIT_CALLBACK_PORT, FITBIT_REDIRECT_URI,
            FITBIT_RATE_LIMIT,
        )
        assert FITBIT_API_BASE == "https://api.fitbit.com"
        assert "oauth2/authorize" in FITBIT_AUTH_URL
        assert "oauth2/token" in FITBIT_TOKEN_URL
        assert "activity" in FITBIT_SCOPES
        assert "heartrate" in FITBIT_SCOPES
        assert "sleep" in FITBIT_SCOPES
        assert FITBIT_CALLBACK_PORT == 8080
        assert "localhost:8080" in FITBIT_REDIRECT_URI
        assert FITBIT_RATE_LIMIT == 150

    def test_range_limits(self):
        from fitbit_mcp.config import (
            MAX_RANGE_DAYS, SLEEP_MAX_RANGE_DAYS,
            WEIGHT_MAX_RANGE_DAYS, SPO2_MAX_RANGE_DAYS, HRV_MAX_RANGE_DAYS,
        )
        assert MAX_RANGE_DAYS == 365
        assert SLEEP_MAX_RANGE_DAYS == 100
        assert WEIGHT_MAX_RANGE_DAYS == 31
        assert SPO2_MAX_RANGE_DAYS == 30
        assert HRV_MAX_RANGE_DAYS == 30


class TestConfigOverrides:
    """Test environment variable overrides."""

    def test_config_dir_override(self, tmp_path):
        with patch.dict(os.environ, {"FITBIT_MCP_CONFIG_DIR": str(tmp_path)}):
            # Re-import to pick up env var
            import importlib
            import fitbit_mcp.config
            importlib.reload(fitbit_mcp.config)
            assert fitbit_mcp.config.CONFIG_DIR == tmp_path
            # Restore
            importlib.reload(fitbit_mcp.config)

    def test_db_path_override(self, tmp_path):
        db_path = tmp_path / "custom.db"
        with patch.dict(os.environ, {"FITBIT_MCP_DB_PATH": str(db_path)}):
            import importlib
            import fitbit_mcp.config
            importlib.reload(fitbit_mcp.config)
            assert fitbit_mcp.config.DB_PATH == db_path
            importlib.reload(fitbit_mcp.config)
