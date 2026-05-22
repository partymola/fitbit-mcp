"""Shared utilities for the Fitbit MCP server."""

import functools
import json
import re
from datetime import date, timedelta
from typing import Any

from . import config
from .api import FitbitOfflineError
from .config import FITBIT_CONFIG_PATH, FITBIT_TOKENS_PATH

# --- Response formatting ---


def format_response(result: Any) -> str:
    """JSON-serialize a result for MCP transport."""
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2, default=str)
    elif result is None:
        return json.dumps(None)
    else:
        return json.dumps({"result": str(result)})


# --- Date parsing with coercion ---

_RELATIVE_RE = re.compile(r"^(\d+)d$")


def parse_date(
    start_str: str | None,
    end_str: str | None = None,
    default_days: int = 30,
) -> tuple[date, date]:
    """Parse flexible date inputs into a (start_date, end_date) tuple.

    Accepted formats:
        "YYYY-MM-DD"  -> exact date
        "YYYY-MM"     -> first of month (start) or last of month (end)
        "30d"         -> 30 days ago from today
        None          -> default_days ago from today (start) or today (end)

    Returns (start_date, end_date) as date objects.
    """
    today = date.today()
    end_date = _parse_single_date(end_str, today, is_end=True)
    start_date = _parse_single_date(start_str, today - timedelta(days=default_days), is_end=False)
    return start_date, end_date


def _parse_single_date(date_str: str | None, default: date, is_end: bool) -> date:
    """Parse a single date string."""
    if date_str is None:
        return default

    # Relative: "30d", "7d", etc.
    m = _RELATIVE_RE.match(date_str)
    if m:
        return date.today() - timedelta(days=int(m.group(1)))

    # Month: "2026-04"
    if re.match(r"^\d{4}-\d{2}$", date_str):
        year, month = int(date_str[:4]), int(date_str[5:7])
        if is_end:
            if month == 12:
                return date(year + 1, 1, 1) - timedelta(days=1)
            return date(year, month + 1, 1) - timedelta(days=1)
        return date(year, month, 1)

    # Full date: "2026-04-15"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date.fromisoformat(date_str)

    raise ValueError(f"Invalid date '{date_str}'. Use YYYY-MM-DD, YYYY-MM, or Nd (e.g. '30d').")


# --- Formatting helpers ---


def format_duration(minutes: int | float | None) -> str:
    """Convert minutes to human-readable duration."""
    if minutes is None:
        return ""
    minutes = round(minutes)
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


# --- Auth decorator ---

# Empty-cache results carry a "Try live=True" hint (wording varies per tool).
# In offline mode live=True is unavailable, so any such hint is rewritten on
# the way out (see _annotate_offline).
_OFFLINE_HINT = (
    "Offline mode is on (FITBIT_MCP_OFFLINE); the host that owns the cache must "
    "sync this period. Live fetch is disabled here."
)


def _annotate_offline(result: str) -> str:
    """Tag a successful offline response and correct the now-wrong live hint.

    Only applied in offline mode. Non-JSON or non-dict payloads pass through
    unchanged.
    """
    try:
        parsed = json.loads(result)
    except (TypeError, ValueError):
        return result
    if not isinstance(parsed, dict):
        return result
    parsed["offline_mode"] = True
    hint = parsed.get("hint")
    if isinstance(hint, str) and "live=True" in hint:
        parsed["hint"] = _OFFLINE_HINT
    return json.dumps(parsed, indent=2, default=str)


def require_auth(func):
    """Gate a tool on credentials, with offline/cache-only support.

    Normal mode: return a "not configured" error if the credential files are
    missing, otherwise call the tool unchanged.

    Offline mode (FITBIT_MCP_OFFLINE): skip the credential check so cache reads
    work without a token; any attempted live API call raises FitbitOfflineError,
    which becomes a clean message; successful responses are tagged offline_mode.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        if not config.OFFLINE_MODE:
            if not FITBIT_CONFIG_PATH.exists() or not FITBIT_TOKENS_PATH.exists():
                return json.dumps(
                    {
                        "error": "Fitbit not configured. Run: fitbit-mcp auth",
                    }
                )
            return await func(*args, **kwargs)

        try:
            result = await func(*args, **kwargs)
        except FitbitOfflineError as e:
            return format_response({"error": str(e), "offline_mode": True})
        return _annotate_offline(result)

    return wrapper
