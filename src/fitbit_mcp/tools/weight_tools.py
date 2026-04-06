"""Weight query tool."""

from datetime import timedelta

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth, parse_date
from .. import api, db
from .sync_tools import auto_sync_if_stale


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch weight data directly from the API."""
    from ..config import WEIGHT_MAX_RANGE_DAYS
    results = {}
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=WEIGHT_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1/user/-/body/log/weight/date/{d}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("weight", []):
            ds = entry.get("date")
            if ds:
                results[ds] = {
                    "date": ds,
                    "weight_kg": entry.get("weight"),
                    "bmi": entry.get("bmi"),
                    "fat_pct": entry.get("fat"),
                }
        d = chunk_end + timedelta(days=1)
    return sorted(results.values(), key=lambda x: x["date"])


@mcp.tool()
@require_auth
async def fitbit_get_weight(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get weight log entries (weight, BMI, body fat percentage).

    Returns data from the local cache by default. Use live=True to fetch
    from Fitbit API. Run fitbit_sync first to populate the cache.

    Weight data is sparse: only days with weigh-in entries are present.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per weigh-in with weight_kg, bmi, fat_pct.
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("weight"))
        def _query():
            conn = db.get_db()
            rows = db.query_weight(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows
        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response({
            "message": "No weight data found for this period.",
            "hint": "Try live=True to fetch directly from the API.",
        })

    return format_response({"weight": entries, "count": len(entries)})
