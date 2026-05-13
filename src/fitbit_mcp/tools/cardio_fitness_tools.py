"""Cardio Fitness Score (VO2 Max) query tool."""

from datetime import timedelta

import anyio

from .. import api, db
from ..helpers import format_response, parse_date, require_auth
from ..mcp_instance import mcp
from .sync_tools import _parse_vo2_max, auto_sync_if_stale


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch cardio fitness (VO2 Max) data directly from the API."""
    from ..config import CARDIO_FITNESS_MAX_RANGE_DAYS

    results = {}
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=CARDIO_FITNESS_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1/user/-/cardioscore/date/{d}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("cardioScore", []):
            ds = entry.get("dateTime")
            value = entry.get("value", {}) or {}
            if not ds:
                continue
            lo, hi = _parse_vo2_max(value.get("vo2Max"))
            if lo is None and hi is None:
                continue
            results[ds] = {
                "date": ds,
                "vo2_max_low": lo,
                "vo2_max_high": hi,
            }
        d = chunk_end + timedelta(days=1)
    return sorted(results.values(), key=lambda x: x["date"])


@mcp.tool()
@require_auth
async def fitbit_get_cardio_fitness(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get Cardio Fitness Score (VO2 Max estimate).

    Fitbit estimates VO2 Max from resting HR, HR during walks/runs, and demographics.
    Updates roughly weekly. Returns from cache by default, auto-syncing if stale.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns entries with vo2_max_low and vo2_max_high (mL/kg/min).
    Fitbit reports as a range (e.g. 39-43); when a single value is given,
    low and high are equal. Higher = better cardiorespiratory fitness.
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("cardio_fitness"))

        def _query():
            conn = db.get_db()
            rows = db.query_cardio_fitness(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows

        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response(
            {
                "message": "No cardio fitness data found for this period.",
                "hint": "Try live=True. Requires age/sex profile and recent walking/running data.",
            }
        )

    return format_response({"cardio_fitness": entries, "count": len(entries)})
