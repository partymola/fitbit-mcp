"""Heart rate query tool."""

from datetime import timedelta

import anyio

from ..mcp_instance import mcp
from ..helpers import format_response, require_auth, parse_date
from .. import api, db


def _fetch_live(start_date, end_date) -> list[dict]:
    """Fetch heart rate data directly from the API."""
    from ..config import MAX_RANGE_DAYS
    results = []
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=MAX_RANGE_DAYS - 1), end_date)
        path = f"/1/user/-/activities/heart/date/{d}/{chunk_end}.json"
        data = api.get(path)
        for entry in data.get("activities-heart", []):
            value = entry.get("value", {})
            results.append({
                "date": entry["dateTime"],
                "resting_hr": value.get("restingHeartRate"),
                "zones": value.get("heartRateZones", []),
            })
        d = chunk_end + timedelta(days=1)
    return results


@mcp.tool()
@require_auth
async def fitbit_get_heart_rate(
    start_date: str | None = None,
    end_date: str | None = None,
    live: bool = False,
) -> str:
    """Get daily resting heart rate and heart rate zones.

    Returns resting HR and zone breakdown (Out of Range, Fat Burn, Cardio, Peak)
    from the local cache by default. Use live=True to fetch from Fitbit API.
    Run fitbit_sync first to populate the cache.

    Args:
        start_date: Start date as "YYYY-MM-DD", "YYYY-MM", or "30d". Default: last 30 days.
        end_date: End date as "YYYY-MM-DD". Default: today.
        live: If true, fetch directly from Fitbit API instead of cache.

    Returns one entry per day with resting_hr and zones array.
    Zone data: name, minutes, caloriesOut, max/min HR for each zone.
    """
    start, end = parse_date(start_date, end_date, default_days=30)

    if live:
        entries = await anyio.to_thread.run_sync(lambda: _fetch_live(start, end))
    else:
        def _query():
            conn = db.get_db()
            rows = db.query_heart_rate(conn, start.isoformat(), end.isoformat())
            conn.close()
            return rows
        entries = await anyio.to_thread.run_sync(_query)

    if not entries:
        return format_response({
            "message": "No heart rate data found for this period.",
            "hint": "Run fitbit_sync first, or try live=True.",
        })

    return format_response({"heart_rate": entries, "count": len(entries)})
