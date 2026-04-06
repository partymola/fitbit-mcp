"""Sleep data query tool."""

from datetime import timedelta

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth, parse_date
from .. import api, db
from .sync_tools import auto_sync_if_stale


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch sleep data directly from the API."""
    from ..config import SLEEP_MAX_RANGE_DAYS
    results = {}
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=SLEEP_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1.2/user/-/sleep/date/{d}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("sleep", []):
            ds = entry.get("dateOfSleep")
            if not ds:
                continue
            minutes = entry.get("minutesAsleep", 0)
            # Keep the longest sleep entry per night
            if ds in results and minutes <= (results[ds].get("total_minutes") or 0):
                continue
            stages = entry.get("levels", {}).get("summary", {})
            results[ds] = {
                "date": ds,
                "total_minutes": entry.get("minutesAsleep"),
                "efficiency": entry.get("efficiency"),
                "start_time": entry.get("startTime"),
                "end_time": entry.get("endTime"),
                "deep_minutes": (stages.get("deep") or {}).get("minutes"),
                "light_minutes": (stages.get("light") or {}).get("minutes"),
                "rem_minutes": (stages.get("rem") or {}).get("minutes"),
                "wake_minutes": (stages.get("wake") or {}).get("minutes"),
            }
        d = chunk_end + timedelta(days=1)
    return sorted(results.values(), key=lambda x: x["date"])


@mcp.tool()
@require_auth
async def fitbit_get_sleep(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get nightly sleep data (duration, stages, efficiency).

    Returns sleep data from the local cache by default. Use live=True
    to fetch from Fitbit API. Run fitbit_sync first to populate the cache.

    Sleep data is sparse: only nights with watch-tracked sleep are present.
    Travel, off-wrist nights, or manual logs may be missing.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per night with total_minutes, efficiency, start/end times,
    and stage breakdown (deep, light, REM, wake minutes).
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("sleep"))
        def _query():
            conn = db.get_db()
            rows = db.query_sleep(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows
        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response({
            "message": "No sleep data found for this period.",
            "hint": "Try live=True to fetch directly from the API.",
        })

    return format_response({"sleep": entries, "count": len(entries)})
