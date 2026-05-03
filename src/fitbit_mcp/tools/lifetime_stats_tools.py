"""Lifetime activity stats and daily goals (live only - no caching)."""

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth
from .. import api


def _fetch_lifetime() -> dict:
    """Fetch all-time activity totals and personal best records."""
    data = api.get("/1/user/-/activities.json")
    lifetime = data.get("lifetime", {}) or {}
    best = data.get("best", {}) or {}
    return {
        "lifetime_total": lifetime.get("total", {}),
        "lifetime_tracker": lifetime.get("tracker", {}),
        "best_total": best.get("total", {}),
        "best_tracker": best.get("tracker", {}),
    }


def _fetch_goals(period: str) -> dict:
    """Fetch user-set activity goals for the given period (daily or weekly)."""
    data = api.get(f"/1/user/-/activities/goals/{period}.json")
    return data.get("goals", {}) or {}


@mcp.tool()
@require_auth
async def fitbit_get_lifetime_stats() -> str:
    """Get all-time activity totals and personal best records.

    Live-only (no caching). Returns lifetime totals (steps, distance, floors,
    calories, active score) and personal bests (best day for steps, distance,
    floors), each with the date the record was set.

    Useful for long-term context that the daily activity table can't easily
    answer (e.g. "what's my best step day ever?").
    """
    result = await anyio.to_thread.run_sync(_fetch_lifetime)
    return format_response(result)


@mcp.tool()
@require_auth
async def fitbit_get_goals(period: str = "daily") -> str:
    """Get user-set activity goals for steps, distance, calories, etc.

    Live-only (no caching). Use to compare actuals (from fitbit_get_activity)
    against the targets the user set in the Fitbit app.

    Args:
        period: "daily" or "weekly". Default: "daily".

    Returns goals dict with keys like steps, distance, calories_out,
    active_minutes, active_zone_minutes, floors. Weekly omits some fields.
    """
    if period not in ("daily", "weekly"):
        return format_response({"error": "period must be 'daily' or 'weekly'"})

    goals = await anyio.to_thread.run_sync(lambda: _fetch_goals(period))
    return format_response({"period": period, "goals": goals})
