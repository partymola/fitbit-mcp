"""Active Zone Minutes (AZM) query tool."""

from datetime import timedelta

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth, parse_date
from .. import api, db
from .sync_tools import auto_sync_if_stale


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch AZM data directly from the API."""
    from ..config import AZM_MAX_RANGE_DAYS
    results = {}
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=AZM_MAX_RANGE_DAYS - 1), end_date)
        path = f"/1/user/-/activities/active-zone-minutes/date/{d}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("activities-active-zone-minutes", []):
            ds = entry.get("dateTime")
            value = entry.get("value", {}) or {}
            if not ds:
                continue
            results[ds] = {
                "date": ds,
                "total_minutes": value.get("activeZoneMinutes"),
                "fat_burn_minutes": value.get("fatBurnActiveZoneMinutes"),
                "cardio_minutes": value.get("cardioActiveZoneMinutes"),
                "peak_minutes": value.get("peakActiveZoneMinutes"),
            }
        d = chunk_end + timedelta(days=1)
    return sorted(results.values(), key=lambda x: x["date"])


@mcp.tool()
@require_auth
async def fitbit_get_azm(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get daily Active Zone Minutes (AZM) - Fitbit's headline cardio metric.

    AZM counts minutes spent in heart rate zones at or above Fat Burn intensity.
    Cardio and Peak zone minutes count double. Returns from local cache by default,
    auto-syncing if stale. Use live=True to bypass the cache.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per day with total_minutes plus per-zone breakdown
    (fat_burn_minutes, cardio_minutes, peak_minutes).
    Distinct from active_minutes in fitbit_get_activity, which counts wall-clock
    minutes regardless of intensity.
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        await anyio.to_thread.run_sync(lambda: auto_sync_if_stale("azm"))
        def _query():
            conn = db.get_db()
            rows = db.query_azm(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows
        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response({
            "message": "No AZM data found for this period.",
            "hint": "Try live=True to fetch directly from the API.",
        })

    return format_response({"azm": entries, "count": len(entries)})
