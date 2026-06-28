"""Configuration paths and constants for the Fitbit MCP server."""

import os
from pathlib import Path

# Default config and data paths (XDG-compatible; override via environment variables)
_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "fitbit-mcp"
_DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "fitbit-mcp" / "fitbit.db"

# Config and data paths (overridable via environment variables)
CONFIG_DIR = Path(os.environ.get("FITBIT_MCP_CONFIG_DIR", _DEFAULT_CONFIG_DIR))
DB_PATH = Path(os.environ.get("FITBIT_MCP_DB_PATH", _DEFAULT_DB_PATH))

# Offline / cache-only mode: when truthy, the server needs no credentials and
# makes no live API calls - it serves the local SQLite cache only. Useful for
# multi-host setups (one host syncs, others read the shared cache), CI, and
# privacy. See the "Offline / cache-only mode" section in the README.
OFFLINE_MODE = os.environ.get("FITBIT_MCP_OFFLINE", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Credential files
FITBIT_CONFIG_PATH = CONFIG_DIR / "fitbit_config.json"
FITBIT_TOKENS_PATH = CONFIG_DIR / "fitbit_tokens.json"

# Fitbit API
FITBIT_API_BASE = "https://api.fitbit.com"
FITBIT_AUTH_URL = "https://www.fitbit.com/oauth2/authorize"
FITBIT_TOKEN_URL = f"{FITBIT_API_BASE}/oauth2/token"

# OAuth
FITBIT_SCOPES = (
    "activity heartrate sleep weight oxygen_saturation profile "
    "respiratory_rate temperature cardio_fitness location nutrition settings"
)
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
AZM_MAX_RANGE_DAYS = 1095
BREATHING_RATE_MAX_RANGE_DAYS = 30
SKIN_TEMPERATURE_MAX_RANGE_DAYS = 30
CORE_TEMPERATURE_MAX_RANGE_DAYS = 30
CARDIO_FITNESS_MAX_RANGE_DAYS = 30

# Canonical list of cached data types - the single source of truth for the
# sync "all" expansion (CLI + fitbit_sync), the CLI --types help, and the
# trends/compare validation messages. Order is the sync order. Add a new
# cached type here once; the lists derived from this update automatically.
# (The per-type sync/trend/query dispatch maps still register each type with
# its own handler, and the tool docstrings restate the list as static prose
# for the LLM - those are intentionally not derived from this.)
CACHED_DATA_TYPES = (
    "heart_rate",
    "activity",
    "exercises",
    "sleep",
    "weight",
    "spo2",
    "hrv",
    "azm",
    "breathing_rate",
    "skin_temperature",
    "core_temperature",
    "cardio_fitness",
    "food_log",
)
