"""Configuration paths and constants for the Fitbit MCP server."""

import os
from pathlib import Path

# Default config and data paths (XDG-compatible; override via environment variables)
_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "fitbit-mcp"
_DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "fitbit-mcp" / "fitbit.db"

# Config and data paths (overridable via environment variables)
CONFIG_DIR = Path(os.environ.get("FITBIT_MCP_CONFIG_DIR", _DEFAULT_CONFIG_DIR))
DB_PATH = Path(os.environ.get("FITBIT_MCP_DB_PATH", _DEFAULT_DB_PATH))

# Credential files
FITBIT_CONFIG_PATH = CONFIG_DIR / "fitbit_config.json"
FITBIT_TOKENS_PATH = CONFIG_DIR / "fitbit_tokens.json"

# Fitbit API
FITBIT_API_BASE = "https://api.fitbit.com"
FITBIT_AUTH_URL = "https://www.fitbit.com/oauth2/authorize"
FITBIT_TOKEN_URL = f"{FITBIT_API_BASE}/oauth2/token"

# OAuth
FITBIT_SCOPES = "activity heartrate sleep weight oxygen_saturation profile"
FITBIT_CALLBACK_PORT = 8080
FITBIT_REDIRECT_URI = f"http://localhost:{FITBIT_CALLBACK_PORT}"

# Rate limiting
FITBIT_RATE_LIMIT = 150  # requests per hour

# API range limits
MAX_RANGE_DAYS = 365  # heart rate time series
SLEEP_MAX_RANGE_DAYS = 100
WEIGHT_MAX_RANGE_DAYS = 31
SPO2_MAX_RANGE_DAYS = 30
HRV_MAX_RANGE_DAYS = 30
